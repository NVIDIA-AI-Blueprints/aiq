// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useDeepResearch Hook
 *
 * Manages the SSE connection lifecycle for deep research jobs.
 * Automatically connects when a job ID is set in the store,
 * routes events to appropriate UI components, and handles reconnection.
 * Includes timeout detection for hung jobs.
 */

'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import {
  createDeepResearchClient,
  cancelJob,
  type DeepResearchClient,
  type DeepResearchJobStatus,
  type TodoItem,
} from '@/adapters/api'
import { useChatStore } from '../store'
import { useAuth } from '@/adapters/auth'
import { useLayoutStore } from '@/features/layout/store'
import { checkBackendHealthCached } from '@/shared/hooks/use-backend-health'

/** Timeout in milliseconds before showing a warning (60 seconds) */
const TIMEOUT_WARNING_MS = 60000
/** How often to check for timeouts (10 seconds) */
const TIMEOUT_CHECK_INTERVAL_MS = 10000
/** Fallback timeout after cancel POST succeeds: if SSE doesn't deliver
 *  job.status "interrupted" within this window, clean up locally so the
 *  UI never stays stuck in a streaming state. */
const CANCEL_FALLBACK_TIMEOUT_MS = 5000

interface UseDeepResearchReturn {
  /** Whether deep research is currently streaming */
  isStreaming: boolean
  /** Current job ID */
  jobId: string | null
  /** Current job status */
  status: DeepResearchJobStatus | null
  /** Whether we're showing a timeout warning (no events received for too long) */
  isTimedOut: boolean
  /** Manually disconnect from the stream */
  disconnect: () => void
  /** Manually reconnect to the stream (uses last event ID) */
  reconnect: () => void
  /** Cancel the current job (useful for hung jobs) */
  cancelCurrentJob: () => Promise<void>
}

/**
 * Hook for managing deep research SSE streaming
 *
 * Automatically:
 * - Connects when deepResearchJobId is set in the store
 * - Routes SSE events to appropriate store actions
 * - Updates UI state (report, citations, thinking steps)
 * - Handles completion and errors
 */
export const useDeepResearch = (): UseDeepResearchReturn => {
  // Refs for SSE client lifecycle
  const clientRef = useRef<DeepResearchClient | null>(null)
  const connectRef = useRef<((jobId: string, bufferReplay?: boolean) => void) | null>(null)
  const lastEventTimeRef = useRef<number>(Date.now())
  const timeoutIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const cancelFallbackRef = useRef<NodeJS.Timeout | null>(null)
  const researchStartTimeRef = useRef<number | null>(null)


  // State for timeout warning
  const [isTimedOut, setIsTimedOut] = useState(false)

  // Auth token for authenticated requests
  // Note: idToken is used for backend auth, not accessToken
  const { idToken } = useAuth()

  // Chat store state and actions
  const {
    deepResearchJobId,
    isDeepResearchStreaming,
    deepResearchStatus,
    updateDeepResearchStatus,
    completeDeepResearch,
    addDeepResearchCitation,
    setReportContent,
    addThinkingStep,
    appendToThinkingStep,
    completeThinkingStep,
    setCurrentStatus,
    setStreaming,
    setDeepResearchTodos,
    stopAllDeepResearchSpinners,
    // New dedicated actions for ThinkingTab sub-tabs
    addDeepResearchLLMStep,
    appendToDeepResearchLLMStep,
    completeDeepResearchLLMStep,
    addDeepResearchAgentWithId,
    completeDeepResearchAgent,
    addDeepResearchToolCall,
    completeDeepResearchToolCall,
    addDeepResearchFile,
    // Actions for message patching
    patchConversationMessage,
    // Actions for deep research banners
    addDeepResearchBanner,
    setStreamLoaded,
  } = useChatStore()

  /**
   * Check if the current session owns the active deep research stream.
   * This prevents SSE events from mutating the wrong session.
   */
  const isOwnerActive = useCallback((): boolean => {
    const state = useChatStore.getState()
    return Boolean(
      state.isDeepResearchStreaming &&
        state.deepResearchOwnerConversationId &&
        state.currentConversation?.id === state.deepResearchOwnerConversationId
    )
  }, [])

  // Layout store for opening research panel
  const { openRightPanel, setResearchPanelTab } = useLayoutStore()

  // Ref to track active thinking step IDs by name
  const activeStepIdsRef = useRef<Map<string, string>>(new Map())

  /**
   * Reset the timeout tracker - called when we receive any live event.
   */
  const resetTimeout = useCallback(() => {
    lastEventTimeRef.current = Date.now()
    setIsTimedOut(false)
  }, [])

  /**
   * Create and connect to the SSE stream
   */
  /**
   * Connect to the SSE stream from the beginning.
   *
   * Single connection, two internal phases:
   * 1. Buffer phase: all replayed events accumulate in plain JS objects (zero store writes).
   *    After 500ms of silence the buffer is flushed in one useChatStore.setState() call.
   * 2. Live phase: subsequent events go straight to individual store actions (fine for low volume).
   */
  const connect = useCallback(
    (jobId: string, bufferReplay = false) => {
      if (clientRef.current) {
        clientRef.current.disconnect()
        clientRef.current = null
      }

      activeStepIdsRef.current.clear()
      resetTimeout()

      // ---------- inline buffer for replay phase ----------
      // bufferReplay=true on page-refresh reconnect: buffer ALL replayed events
      // with zero store writes (like streamFullJob). The backend sends a
      // stream.mode event with mode="live" when replay is done. On that signal,
      // flush the buffer in one setState and switch to per-event live streaming.
      // A safety timeout (30s) flushes if the signal never arrives.
      // bufferReplay=false for fresh new jobs: events go straight to store.
      const SAFETY_TIMEOUT_MS = 30000
      const buf = {
        active: bufferReplay,
        timer: null as NodeJS.Timeout | null,
        idCounter: 0,
        activeLLMStack: [] as string[],
        activeToolStacks: new Map<string, string[]>(),
        agents: new Map<string, { name: string; input?: string; output?: string }>(),
        llmSteps: new Map<string, { name: string; workflow?: string; content: string; thinking?: string; usage?: { input_tokens: number; output_tokens: number } }>(),
        toolCalls: new Map<string, { name: string; input?: Record<string, unknown>; output?: string; workflow?: string; agentId?: string }>(),
        todos: null as TodoItem[] | null,
        citations: [] as Array<{ url: string; content: string; isCited: boolean }>,
        files: new Map<string, string>(),
        reportContent: null as string | null,
      }

      /** Flush buffer to store in one setState, deactivate buffer, switch to live. */
      const flushBuffer = (): void => {
        if (!buf.active) return
        buf.active = false
        if (buf.timer) { clearTimeout(buf.timer); buf.timer = null }

        const now = new Date()
        const agents = Array.from(buf.agents.entries()).map(([id, a]) => ({ id, name: a.name, input: a.input, output: a.output, status: 'complete' as const, startedAt: now, completedAt: now }))
        const llmSteps = Array.from(buf.llmSteps.entries()).map(([id, s]) => ({ id, name: s.name, workflow: s.workflow, content: s.content, thinking: s.thinking, usage: s.usage, isComplete: true, timestamp: now }))
        const toolCalls = Array.from(buf.toolCalls.entries()).map(([id, t]) => ({ id, name: t.name, input: t.input, output: t.output, workflow: t.workflow, agentId: t.agentId, status: 'complete' as const, timestamp: now }))
        const citations = buf.citations.map((c, i) => ({ id: `citation-${i}`, url: c.url, content: c.content, isCited: c.isCited, timestamp: now }))
        const files = Array.from(buf.files.entries()).map(([filename, content], i) => ({ id: `file-${i}`, filename, content, timestamp: now }))
        const todos = buf.todos?.map((t, i) => ({ id: `todo-${i}-${t.content.substring(0, 20).replace(/\s+/g, '-').toLowerCase()}`, content: t.content, status: t.status as 'pending' | 'in_progress' | 'completed' | 'stopped' }))

        useChatStore.setState((state) => ({
          ...(buf.reportContent !== null && { reportContent: buf.reportContent }),
          ...(todos && todos.length > 0 && { deepResearchTodos: todos }),
          ...(agents.length > 0 && { deepResearchAgents: agents }),
          ...(llmSteps.length > 0 && { deepResearchLLMSteps: llmSteps }),
          ...(toolCalls.length > 0 && { deepResearchToolCalls: toolCalls }),
          ...(citations.length > 0 && { deepResearchCitations: citations }),
          ...(files.length > 0 && { deepResearchFiles: files }),
          currentStatus: buf.reportContent !== null ? 'writing' : state.currentStatus,
        }))

        // Bridge in-progress items to live mode so their end events
        // (llm.end with usage, tool.end with output) can find them
        for (const id of buf.activeLLMStack) {
          const step = buf.llmSteps.get(id)
          if (step) {
            activeStepIdsRef.current.set(`llm:${step.name}`, id)
            activeStepIdsRef.current.set(`llmStep:${step.name}`, id)
          }
        }
        for (const [name, stack] of buf.activeToolStacks) {
          const lastId = stack[stack.length - 1]
          if (lastId) {
            activeStepIdsRef.current.set(`tool:${name}`, lastId)
            activeStepIdsRef.current.set(`toolCall:${name}`, lastId)
          }
        }
      }

      // Safety timeout: flush if the backend never sends the live signal
      if (bufferReplay) {
        buf.timer = setTimeout(flushBuffer, SAFETY_TIMEOUT_MS)
      }

      // Create SSE client — callbacks check buf.active to decide buffer vs real-time
      const client = createDeepResearchClient({
        jobId,
        authToken: idToken || undefined,
        callbacks: {
          onStreamStart: () => {
            if (buf.active) return
            if (!isOwnerActive()) return
            resetTimeout()
            researchStartTimeRef.current = Date.now()
            setCurrentStatus('researching')
          },

          onStreamMode: (mode) => {
            if (mode === 'live' && buf.active) {
              flushBuffer()
              setCurrentStatus('researching')
            }
          },

          onJobStatus: (status, error) => {
            if (buf.active) flushBuffer()
            if (!isOwnerActive()) return
            resetTimeout()
            // Clear the cancel-fallback timer — the SSE stream delivered
            // the terminal status so optimistic cleanup is unnecessary.
            if (cancelFallbackRef.current) {
              clearTimeout(cancelFallbackRef.current)
              cancelFallbackRef.current = null
            }
            updateDeepResearchStatus(status)

            const state = useChatStore.getState()
            const ownerConvId = state.deepResearchOwnerConversationId
            const messageId = state.activeDeepResearchMessageId

            if (status === 'success') {
              setCurrentStatus('complete')
              const { reportContent: currentReport, deepResearchLLMSteps, deepResearchToolCalls } = state
              const totalTokens = deepResearchLLMSteps.reduce((sum, step) => sum + (step.usage?.input_tokens || 0) + (step.usage?.output_tokens || 0), 0)
              const toolCallCount = deepResearchToolCalls.length
              const hasReport = Boolean(currentReport?.trim())

              if (ownerConvId && messageId) {
                patchConversationMessage(ownerConvId, messageId, {
                  content: '',
                  deepResearchJobStatus: 'success',
                  isDeepResearchActive: false,
                  showViewReport: hasReport,
                })
              }
              addDeepResearchBanner('success', jobId, ownerConvId || undefined, { totalTokens, toolCallCount })
              researchStartTimeRef.current = null
              stopAllDeepResearchSpinners(true)
              setStreamLoaded(true)
              completeDeepResearch()
              setStreaming(false)
            } else if (status === 'failure' || status === 'interrupted') {
              setCurrentStatus('error')
              stopAllDeepResearchSpinners()
              const hasReport = Boolean(state.reportContent?.trim())

              if (ownerConvId && messageId) {
                patchConversationMessage(ownerConvId, messageId, {
                  content: '',
                  deepResearchJobStatus: status,
                  isDeepResearchActive: false,
                  showViewReport: hasReport,
                })
              }
              const isUserCancelled = status === 'interrupted'
              addDeepResearchBanner(isUserCancelled ? 'cancelled' : 'failure', jobId, ownerConvId || undefined)
              researchStartTimeRef.current = null
              clientRef.current?.disconnect()
              setStreamLoaded(true)
              completeDeepResearch()
              setStreaming(false)
              if (error && !isUserCancelled) {
                const { addErrorCard } = useChatStore.getState()
                addErrorCard('agent.deep_research_failed', error)
              }
            }
          },

          onHeartbeat: () => {
            if (buf.active) return
            if (!isOwnerActive()) return
            resetTimeout()
          },

          onWorkflowStart: (name, input, eventId, agentId) => {
            const id = agentId || eventId || `agent-${buf.idCounter++}`
            if (buf.active) {
              if (!buf.agents.has(id)) buf.agents.set(id, { name, input: input ? (typeof input === 'string' ? input : JSON.stringify(input)) : undefined })
              return
            }
            if (!isOwnerActive()) return
            resetTimeout()
            const hasUserMsg = Boolean(useChatStore.getState().currentUserMessageId)
            if (hasUserMsg) {
              const stepId = addThinkingStep({ category: 'agents', functionName: name, displayName: name, content: input ? `Input: ${input}\n` : 'Starting...\n', isComplete: false, isDeepResearch: true })
              activeStepIdsRef.current.set(name, stepId)
            }
            const createdId = addDeepResearchAgentWithId(id, { name, input })
            activeStepIdsRef.current.set(`agent:${id}`, createdId)
          },

          onWorkflowEnd: (name, output, _eventId, agentId) => {
            if (buf.active) {
              if (agentId) { const a = buf.agents.get(agentId); if (a) a.output = output ? (typeof output === 'string' ? output : JSON.stringify(output)) : undefined }
              return
            }
            if (!isOwnerActive()) return
            const stepId = activeStepIdsRef.current.get(name)
            if (stepId) { if (output) appendToThinkingStep(stepId, `\nOutput: ${output}`); completeThinkingStep(stepId); activeStepIdsRef.current.delete(name) }
            if (agentId) { completeDeepResearchAgent(agentId, output); activeStepIdsRef.current.delete(`agent:${agentId}`) }
          },

          onLLMStart: (name, workflow) => {
            if (buf.active) {
              const id = `llm-${buf.idCounter++}`; buf.activeLLMStack.push(id); buf.llmSteps.set(id, { name, workflow, content: '' }); return
            }
            if (!isOwnerActive()) return

            const hasUserMsg = Boolean(useChatStore.getState().currentUserMessageId)
            if (hasUserMsg) {
              const displayName = workflow ? `${workflow} > ${name}` : name
              const stepId = addThinkingStep({ category: 'agents', functionName: `llm:${name}`, displayName, content: 'Generating...\n', isComplete: false, isDeepResearch: true })
              activeStepIdsRef.current.set(`llm:${name}`, stepId)
            }
            const llmStepId = addDeepResearchLLMStep({ name, workflow, content: '' })
            activeStepIdsRef.current.set(`llmStep:${name}`, llmStepId)
          },

          onLLMChunk: (chunk) => {
            if (buf.active) {
              const id = buf.activeLLMStack[buf.activeLLMStack.length - 1]; if (id) { const s = buf.llmSteps.get(id); if (s) s.content += chunk }; return
            }
            if (!isOwnerActive()) return
            resetTimeout()
            const llmStepId = Array.from(activeStepIdsRef.current.entries()).filter(([k]) => k.startsWith('llm:')).pop()?.[1]
            if (llmStepId) appendToThinkingStep(llmStepId, chunk)
            const llmStepKeys = Array.from(activeStepIdsRef.current.entries()).filter(([k]) => k.startsWith('llmStep:'))
            if (llmStepKeys.length > 0) appendToDeepResearchLLMStep(llmStepKeys[llmStepKeys.length - 1][1], chunk)
          },

          onLLMEnd: (_output, thinking, usage) => {
            if (buf.active) {
              const id = buf.activeLLMStack.pop(); if (id) { const s = buf.llmSteps.get(id); if (s) { s.thinking = thinking; s.usage = usage } }; return
            }
            if (!isOwnerActive()) return
            const llmSteps = Array.from(activeStepIdsRef.current.entries()).filter(([k]) => k.startsWith('llm:'))
            if (llmSteps.length > 0) { const [key, stepId] = llmSteps[llmSteps.length - 1]; if (thinking) appendToThinkingStep(stepId, `\n\nThinking: ${thinking}`); completeThinkingStep(stepId); activeStepIdsRef.current.delete(key) }
            const llmStepKeys = Array.from(activeStepIdsRef.current.entries()).filter(([k]) => k.startsWith('llmStep:'))
            if (llmStepKeys.length > 0) { const [key, llmStepId] = llmStepKeys[llmStepKeys.length - 1]; completeDeepResearchLLMStep(llmStepId, thinking, usage); activeStepIdsRef.current.delete(key) }
          },

          onToolStart: (name, input, workflow, _eventId, agentId) => {
            if (name === 'task') return
            if (buf.active) {
              const id = `tool-${buf.idCounter++}`; buf.toolCalls.set(id, { name, input, workflow, agentId })
              let stack = buf.activeToolStacks.get(name); if (!stack) { stack = []; buf.activeToolStacks.set(name, stack) }; stack.push(id); return
            }
            if (!isOwnerActive()) return
            resetTimeout(); setCurrentStatus('searching')
            const hasUserMsg = Boolean(useChatStore.getState().currentUserMessageId)
            if (hasUserMsg) {
              const inputText = input ? ('_raw' in input && typeof input._raw === 'string' ? input._raw : JSON.stringify(input, null, 2)) : null
              const stepId = addThinkingStep({ category: 'tools', functionName: name, displayName: name, content: inputText ? `Input: ${inputText}\n` : 'Executing...\n', isComplete: false, isDeepResearch: true })
              activeStepIdsRef.current.set(`tool:${name}`, stepId)
            }
            const toolCallId = addDeepResearchToolCall({ name, input, workflow, agentId })
            activeStepIdsRef.current.set(`toolCall:${name}`, toolCallId)
          },

          onToolEnd: (name, output) => {
            if (name === 'task') return
            if (buf.active) {
              const stack = buf.activeToolStacks.get(name); const id = stack?.pop(); if (id) { const t = buf.toolCalls.get(id); if (t) t.output = output ? JSON.stringify(output) : undefined }; return
            }
            if (!isOwnerActive()) return
            const stepId = activeStepIdsRef.current.get(`tool:${name}`)
            if (stepId) { if (output) { const truncated = output.length > 500 ? output.substring(0, 500) + '...' : output; appendToThinkingStep(stepId, `\nOutput: ${truncated}`) }; completeThinkingStep(stepId); activeStepIdsRef.current.delete(`tool:${name}`) }
            const toolCallId = activeStepIdsRef.current.get(`toolCall:${name}`)
            if (toolCallId) { completeDeepResearchToolCall(toolCallId, output); activeStepIdsRef.current.delete(`toolCall:${name}`) }
            setCurrentStatus('researching')
          },

          onTodoUpdate: (todos: TodoItem[]) => {
            if (buf.active) { buf.todos = todos; return }
            if (!isOwnerActive()) return
            resetTimeout(); setDeepResearchTodos(todos)

          },

          onCitationUpdate: (url, content, isCited) => {
            if (buf.active) { buf.citations.push({ url, content, isCited: isCited ?? false }); return }
            if (!isOwnerActive()) return
            resetTimeout(); addDeepResearchCitation(url, content, isCited)
          },

          onFileUpdate: (filename, content) => {
            if (buf.active) { buf.files.set(filename, content); return }
            if (!isOwnerActive()) return
            resetTimeout(); addDeepResearchFile({ filename, content })
            // report.md artifact arrives 1-2 min before the final_report output event —
            // use it as an early signal to switch the UI to "writing" status.
            if (filename.endsWith('report.md')) {
              setCurrentStatus('writing')
            }
          },

          onOutputUpdate: (content, outputCategory, _workflow) => {
            if (outputCategory === 'intermediate') return
            if (buf.active) {
              if (outputCategory === 'final_report' || !outputCategory) { buf.reportContent = content }
              // research_notes are already captured via write_file artifacts — skip to avoid duplicates
              return
            }
            if (!isOwnerActive()) return
            if (outputCategory === 'research_notes') {
              // Skip — research notes are already tracked via write_file tool artifacts
              void 0
            } else if (outputCategory === 'final_report' || !outputCategory) {
              setReportContent(content)
              setCurrentStatus('writing')
            }
          },

          onComplete: () => {
            if (buf.active) flushBuffer()
          },

          onError: async (error) => {
            console.warn('Deep research SSE error:', error.message)
            if (buf.active) flushBuffer()
            const { isDeepResearchStreaming, deepResearchStatus } = useChatStore.getState()
            if (isDeepResearchStreaming && deepResearchStatus !== 'interrupted' && deepResearchStatus !== 'failure') {
              const backendUp = await checkBackendHealthCached()
              if (backendUp) return
              console.error('Deep research SSE failed (backend unreachable):', error)
              const { addErrorCard } = useChatStore.getState()
              addErrorCard('agent.deep_research_failed', error.message, error.stack)
              stopAllDeepResearchSpinners()
            }
          },

          onDisconnect: () => {
            if (buf.active) flushBuffer()
          },
        },
      })

      clientRef.current = client
      client.connect()
    },
    [
      idToken, resetTimeout, isOwnerActive, updateDeepResearchStatus, completeDeepResearch,
      addDeepResearchCitation, setReportContent, addThinkingStep, appendToThinkingStep,
      completeThinkingStep, setCurrentStatus, setDeepResearchTodos, stopAllDeepResearchSpinners,
      addDeepResearchLLMStep, appendToDeepResearchLLMStep,
      completeDeepResearchLLMStep, addDeepResearchAgentWithId, completeDeepResearchAgent,
      addDeepResearchToolCall, completeDeepResearchToolCall, addDeepResearchFile,
      patchConversationMessage, addDeepResearchBanner, setStreaming, setStreamLoaded,
    ]
  )

  // Keep ref in sync so the effect always uses the latest connect without re-triggering
  connectRef.current = connect

  /**
   * Disconnect from the SSE stream
   */
  const disconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect()
      clientRef.current = null
    }
  }, [])

  /**
   * Reconnect to the SSE stream from the beginning
   */
  const reconnect = useCallback(() => {
    if (deepResearchJobId && !clientRef.current?.isConnected()) {
      connectRef.current?.(deepResearchJobId, true)
    }
  }, [deepResearchJobId])

  /**
   * Cancel the current job (useful for hung jobs)
   */
  const cancelCurrentJob = useCallback(async () => {
    if (!deepResearchJobId) return
    const cancelledJobId = deepResearchJobId

    try {
      await cancelJob(cancelledJobId, idToken || undefined)
      setIsTimedOut(false)

      // Fallback: if the SSE stream is broken or stalled and never delivers
      // the job.status: "interrupted" event, clean up locally after a short
      // grace period so the UI doesn't stay stuck in "streaming" state.
      // If the SSE event arrives in time, onJobStatus clears this timer.
      if (cancelFallbackRef.current) clearTimeout(cancelFallbackRef.current)
      cancelFallbackRef.current = setTimeout(() => {
        cancelFallbackRef.current = null
        const state = useChatStore.getState()
        if (!state.isDeepResearchStreaming || state.deepResearchJobId !== cancelledJobId) {
          return // SSE already handled cleanup — nothing to do
        }
        console.warn(
          '[DeepResearch] Cancel fallback: SSE did not deliver interrupted status within',
          CANCEL_FALLBACK_TIMEOUT_MS,
          'ms. Cleaning up locally.'
        )
        const ownerConvId = state.deepResearchOwnerConversationId
        const messageId = state.activeDeepResearchMessageId
        const hasReport = Boolean(state.reportContent?.trim())
        if (ownerConvId && messageId) {
          patchConversationMessage(ownerConvId, messageId, {
            content: '',
            deepResearchJobStatus: 'interrupted',
            isDeepResearchActive: false,
            showViewReport: hasReport,
          })
        }
        addDeepResearchBanner('cancelled', cancelledJobId, ownerConvId || undefined)
        stopAllDeepResearchSpinners()
        clientRef.current?.disconnect()
        clientRef.current = null
        setStreamLoaded(true)
        completeDeepResearch()
        setStreaming(false)
      }, CANCEL_FALLBACK_TIMEOUT_MS)
    } catch (error) {
      console.error('Failed to cancel job:', error)
    }
  }, [deepResearchJobId, idToken, patchConversationMessage, addDeepResearchBanner, stopAllDeepResearchSpinners, completeDeepResearch, setStreaming, setStreamLoaded])

  /**
   * Auto-connect when job ID changes
   * Uses lastEventId from store for reconnection scenarios (session restore, tab reopen)
   */
  useEffect(() => {
    // Capture values at effect start to detect stale effects
    const effectJobId = deepResearchJobId
    const effectStreaming = isDeepResearchStreaming
    let connectTimeout: NodeJS.Timeout | null = null
    let cancelled = false

    if (effectJobId && effectStreaming) {
      // Verify state hasn't changed before connecting (prevents race conditions)
      const currentState = useChatStore.getState()
      if (currentState.deepResearchJobId !== effectJobId || !currentState.isDeepResearchStreaming) {
        return // State changed, don't connect
      }

      // Defer connect by 50ms so React StrictMode cleanup can cancel it.
      // StrictMode sequence: mount1-effect → mount1-cleanup → mount2-effect.
      // The cleanup clears the timeout, preventing mount1 from ever connecting.
      // Only mount2's deferred connect actually fires.
      connectTimeout = setTimeout(async () => {
        if (cancelled) return

        // Determine if this is a reconnection (page refresh) or a fresh job start.
        // Fresh jobs (status 'submitted') use per-event store writes for live updates.
        // Reconnections (status 'running') buffer historical events then flush once
        // when the backend sends stream.mode: "live".
        const isReconnect = useChatStore.getState().deepResearchStatus !== 'submitted'
        connectRef.current?.(effectJobId, isReconnect)

        setResearchPanelTab('tasks')
        openRightPanel('research')

        // Start timeout check interval
        timeoutIntervalRef.current = setInterval(() => {
          const timeSinceLastEvent = Date.now() - lastEventTimeRef.current
          if (timeSinceLastEvent > TIMEOUT_WARNING_MS) {
            setIsTimedOut(true)
          }
        }, TIMEOUT_CHECK_INTERVAL_MS)
      }, 50)

      // Session persistence is now handled by debounced resetTimeout()
      // (fires 2s after each event instead of fixed 10s interval)
    }

    return () => {
      cancelled = true
      // Cancel the deferred connect if it hasn't fired yet
      if (connectTimeout) clearTimeout(connectTimeout)
      // Cleanup on unmount or job ID change
      disconnect()
      // Clear timeout interval
      if (timeoutIntervalRef.current) {
        clearInterval(timeoutIntervalRef.current)
        timeoutIntervalRef.current = null
      }
      // Clear cancel fallback timer
      if (cancelFallbackRef.current) {
        clearTimeout(cancelFallbackRef.current)
        cancelFallbackRef.current = null
      }
      setIsTimedOut(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- connectRef avoids re-triggering on token refresh; store actions are stable refs
  }, [deepResearchJobId, isDeepResearchStreaming, disconnect, setResearchPanelTab, openRightPanel])

  return {
    isStreaming: isDeepResearchStreaming,
    jobId: deepResearchJobId,
    status: deepResearchStatus,
    isTimedOut,
    disconnect,
    reconnect,
    cancelCurrentJob,
  }
}
