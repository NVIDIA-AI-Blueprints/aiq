// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useLoadJobData Hook
 *
 * Loads deep research job data (report, citations, todos, tool calls, etc.)
 * either from the report API endpoint or by replaying the SSE stream.
 *
 * Use cases:
 * - "View Report" button clicks to load data on-demand
 * - Session restoration when reconnecting to completed jobs
 * - Importing historical job data
 *
 * Two primary methods:
 * 1. `loadReport(jobId)` - Quick fetch of just the report text via REST API
 * 2. `importJobStream(jobId)` - Full replay of SSE stream to get all artifacts
 *    (citations, todos, tool calls, agents, files, etc.)
 */

'use client'

import { useState, useCallback, useRef } from 'react'
import {
  getJobReport,
  getJobStatus,
  getJobState,
  createDeepResearchClient,
  type DeepResearchClient,
  type DeepResearchJobStatus,
  type TodoItem,
} from '@/adapters/api'
import { useChatStore } from '../store'
import { isUnavailableDeepResearchJobError } from '../lib/deep-research-errors'
import { useAuth } from '@/adapters/auth'
import { useLayoutStore } from '@/features/layout/store'

export interface LoadJobDataOptions {
  /**
   * Whether to stream the full job to get all artifacts (citations, todos, tool calls, etc.)
   * If false, only fetches the final report via REST API.
   * @default false
   */
  streamFullJob?: boolean
}

export interface UseLoadJobDataReturn {
  /**
   * Load just the report text via REST API (fast, minimal data)
   * Use when you only need the final report content
   */
  loadReport: (jobId: string) => Promise<void>

  /**
   * Import the full job stream to get all artifacts
   * Replays the SSE stream from the beginning to populate:
   * - Report content
   * - Citations (referenced and cited sources)
   * - Todos/tasks
   * - Tool calls with inputs/outputs
   * - Agent/workflow executions
   * - File artifacts
   * - LLM thought traces
   *
   * Use when you need the complete research context, not just the report
   * Opens report tab after completion
   */
  importJobStream: (jobId: string) => Promise<void>

  /**
   * Import stream data only - does NOT change panel tab
   * Use when loading stream data for an already-open tab (e.g., Tasks/Thinking/Citations)
   */
  importStreamOnly: (jobId: string) => Promise<void>

  /**
   * Legacy method - calls either loadReport or importJobStream based on options
   * @deprecated Use loadReport or importJobStream directly for clarity
   */
  loadJobData: (jobId: string, options?: LoadJobDataOptions) => Promise<void>

  /** Whether data is currently being loaded */
  isLoading: boolean

  /** Error message if loading failed */
  error: string | null

  /** Clear any error state */
  clearError: () => void
}

/**
 * Hook for loading deep research job data on-demand
 *
 * Can either:
 * 1. Fetch just the report via REST API (fast, minimal data)
 * 2. Replay the full SSE stream to get all artifacts (comprehensive)
 */
export const useLoadJobData = (): UseLoadJobDataReturn => {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const clientRef = useRef<DeepResearchClient | null>(null)

  const { idToken } = useAuth()
  const {
    setReportContent,
    addDeepResearchToolCall,
    completeDeepResearchToolCall,
    clearDeepResearch,
    setCurrentStatus,
    setLoadedJobId,
    setStreamLoaded,
    stopAllDeepResearchSpinners,
    addErrorCard,
    completeDeepResearch,
    setStreaming,
    patchConversationMessage,
    addDeepResearchBanner,
  } = useChatStore()

  const { openRightPanel, setResearchPanelTab } = useLayoutStore()

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  const syncMissingJobToFailureState = useCallback(
    (jobId: string): void => {
      const state = useChatStore.getState()
      const conversation = state.currentConversation
      if (!conversation) return

      const trackingMessage = [...conversation.messages]
        .reverse()
        .find((m) => m.messageType === 'agent_response' && m.deepResearchJobId === jobId)

      if (trackingMessage?.id) {
        const hasPartialReport = Boolean(
          trackingMessage.reportContent?.trim() || trackingMessage.showViewReport
        )
        patchConversationMessage(conversation.id, trackingMessage.id, {
          deepResearchJobStatus: 'failure',
          isDeepResearchActive: false,
          showViewReport: hasPartialReport,
        })
      }

      const hasTerminalBanner = conversation.messages.some(
        (m) =>
          m.messageType === 'deep_research_banner' &&
          m.deepResearchBannerData?.jobId === jobId &&
          ['success', 'failure', 'cancelled'].includes(m.deepResearchBannerData?.bannerType || '')
      )

      if (!hasTerminalBanner) {
        addDeepResearchBanner('failure', jobId, conversation.id)
      }
    },
    [patchConversationMessage, addDeepResearchBanner]
  )

  /**
   * Load job data using REST API (report only)
   */
  const _loadReportOnly = useCallback(
    async (jobId: string): Promise<boolean> => {
      const response = await getJobReport(jobId, idToken || undefined)

      if (response.has_report && response.report) {
        setReportContent(response.report)
        return true
      }

      return false
    },
    [idToken, setReportContent]
  )

  /**
   * Load job state for additional artifacts (tool calls, outputs)
   * This is faster than streaming but provides less data than full stream replay
   */
  const loadJobState = useCallback(
    async (jobId: string): Promise<void> => {
      try {
        const stateResponse = await getJobState(jobId, idToken || undefined)

        if (stateResponse.has_state && stateResponse.artifacts) {
          const { tools, outputs } = stateResponse.artifacts

          tools?.forEach((tool: { name: string; input?: Record<string, unknown>; output?: string }) => {
            const toolCallId = addDeepResearchToolCall({
              name: tool.name,
              input: tool.input,
              workflow: undefined,
            })
            if (tool.output) {
              completeDeepResearchToolCall(toolCallId, tool.output)
            }
          })

          outputs?.forEach((output: { type: string; content: string }) => {
            if (output.type === 'report' || output.type === 'output') {
              setReportContent(output.content)
            }
          })
        }
      } catch (stateError) {
        console.warn('Failed to load job state:', stateError)
      }
    },
    [idToken, addDeepResearchToolCall, completeDeepResearchToolCall, setReportContent]
  )

  /**
   * Load job data using REST APIs (report + state) - fast approach
   * Fetches both report and state in parallel for speed
   */
  const loadJobDataFast = useCallback(
    async (jobId: string): Promise<void> => {
      const [reportResult] = await Promise.allSettled([
        getJobReport(jobId, idToken || undefined),
        loadJobState(jobId),
      ])

      if (reportResult.status === 'fulfilled' && reportResult.value.has_report && reportResult.value.report) {
        setReportContent(reportResult.value.report)
      }
    },
    [idToken, loadJobState, setReportContent]
  )

  /**
   * Stream the full job from the beginning to get all artifacts.
   * Buffers ALL events in memory and commits to the store in a single
   * setState call when the stream ends, preventing hundreds of individual
   * set() calls that cause render storms and Aw Snap crashes.
   */
  const streamFullJob = useCallback(
    (jobId: string): Promise<void> => {
      return new Promise((resolve, reject) => {
        // Stacks to track active items per name (for matching start/end when events interleave)
        const activeLLMStack: string[] = []
        const activeToolStacks = new Map<string, string[]>()
        let idCounter = 0

        // Accumulation buffer — everything stays here until the stream ends
        const buffer = {
          agents: new Map<string, { name: string; input?: string; output?: string }>(),
          llmSteps: new Map<string, { name: string; workflow?: string; content: string; thinking?: string; usage?: { input_tokens: number; output_tokens: number } }>(),
          toolCalls: new Map<string, { name: string; input?: Record<string, unknown>; output?: string; workflow?: string; agentId?: string }>(),
          todos: null as TodoItem[] | null,
          citations: [] as Array<{ url: string; content: string; isCited: boolean }>,
          files: new Map<string, string>(),  // filename -> latest content (deduped)
          reportContent: null as string | null,
        }

        /**
         * Convert buffer to store-compatible arrays and write everything
         * in a single useChatStore.setState() call.
         */
        const commitToStore = (): void => {
          const now = new Date()

          const agents = Array.from(buffer.agents.entries()).map(([id, a]) => ({
            id,
            name: a.name,
            input: a.input,
            output: a.output,
            status: 'complete' as const,
            startedAt: now,
            completedAt: now,
          }))

          const llmSteps = Array.from(buffer.llmSteps.entries()).map(([id, s]) => ({
            id,
            name: s.name,
            workflow: s.workflow,
            content: s.content,
            thinking: s.thinking,
            usage: s.usage,
            isComplete: true,
            timestamp: now,
          }))

          const toolCalls = Array.from(buffer.toolCalls.entries()).map(([id, t]) => ({
            id,
            name: t.name,
            input: t.input,
            output: t.output,
            workflow: t.workflow,
            agentId: t.agentId,
            status: 'complete' as const,
            timestamp: now,
          }))

          const citations = buffer.citations.map((c, idx) => ({
            id: `citation-${idx}`,
            url: c.url,
            content: c.content,
            isCited: c.isCited,
            timestamp: now,
          }))

          const files = Array.from(buffer.files.entries()).map(([filename, content], idx) => ({
            id: `file-${idx}`,
            filename,
            content,
            timestamp: now,
          }))

          const todos = buffer.todos
            ? buffer.todos.map((t, idx) => ({
                id: `todo-${idx}-${t.content.substring(0, 20).replace(/\s+/g, '-').toLowerCase()}`,
                content: t.content,
                status: t.status as 'pending' | 'in_progress' | 'completed' | 'stopped',
              }))
            : undefined

          useChatStore.setState((state) => ({
            ...(buffer.reportContent !== null && { reportContent: buffer.reportContent }),
            ...(todos && { deepResearchTodos: todos }),
            ...(agents.length > 0 && { deepResearchAgents: agents }),
            ...(llmSteps.length > 0 && { deepResearchLLMSteps: llmSteps }),
            ...(toolCalls.length > 0 && { deepResearchToolCalls: toolCalls }),
            ...(citations.length > 0 && { deepResearchCitations: citations }),
            ...(files.length > 0 && { deepResearchFiles: files }),
            currentStatus: buffer.reportContent !== null ? 'complete' : state.currentStatus,
          }))
        }

        if (clientRef.current) {
          clientRef.current.disconnect()
          clientRef.current = null
        }

        const client = createDeepResearchClient({
          jobId,
          authToken: idToken || undefined,
          callbacks: {
            onStreamStart: () => {
              setCurrentStatus('researching')
            },

            onJobStatus: (status: DeepResearchJobStatus, statusError?: string) => {
              if (status === 'success' || status === 'failure' || status === 'interrupted') {
                clientRef.current?.disconnect()
                clientRef.current = null
                commitToStore()

                if (status === 'failure' && statusError) {
                  reject(new Error(statusError))
                } else {
                  resolve()
                }
              }
            },

            onWorkflowStart: (name, input, _eventId, agentId) => {
              if (!agentId) return
              if (!buffer.agents.has(agentId)) {
                buffer.agents.set(agentId, {
                  name,
                  input: input ? (typeof input === 'string' ? input : JSON.stringify(input)) : undefined,
                })
              }
            },

            onWorkflowEnd: (_name, output, _eventId, agentId) => {
              if (!agentId) return
              const agent = buffer.agents.get(agentId)
              if (agent) {
                agent.output = output ? (typeof output === 'string' ? output : JSON.stringify(output)) : undefined
              }
            },

            onLLMStart: (name, workflow) => {
              const uniqueId = `llm-${idCounter++}`
              activeLLMStack.push(uniqueId)
              buffer.llmSteps.set(uniqueId, { name, workflow, content: '' })
            },

            onLLMChunk: (chunk) => {
              const currentId = activeLLMStack[activeLLMStack.length - 1]
              if (currentId) {
                const step = buffer.llmSteps.get(currentId)
                if (step) {
                  step.content += chunk
                }
              }
            },

            onLLMEnd: (_output, thinking, usage) => {
              const currentId = activeLLMStack.pop()
              if (currentId) {
                const step = buffer.llmSteps.get(currentId)
                if (step) {
                  step.thinking = thinking
                  step.usage = usage
                }
              }
            },

            onToolStart: (name, input, workflow, _eventId, agentId) => {
              if (name === 'task') return
              const uniqueId = `tool-${idCounter++}`
              buffer.toolCalls.set(uniqueId, { name, input, workflow, agentId })
              let stack = activeToolStacks.get(name)
              if (!stack) {
                stack = []
                activeToolStacks.set(name, stack)
              }
              stack.push(uniqueId)
            },

            onToolEnd: (name, output, _eventId, _agentId) => {
              if (name === 'task') return
              const stack = activeToolStacks.get(name)
              const uniqueId = stack?.pop()
              if (uniqueId) {
                const tool = buffer.toolCalls.get(uniqueId)
                if (tool) {
                  tool.output = output ? JSON.stringify(output) : undefined
                }
              }
            },

            onTodoUpdate: (todos: TodoItem[]) => {
              buffer.todos = todos
            },

            onCitationUpdate: (url, content, isCited) => {
              buffer.citations.push({ url, content, isCited: isCited ?? false })
            },

            onFileUpdate: (filename, content) => {
              buffer.files.set(filename, content)
            },

            onOutputUpdate: (content, outputCategory) => {
              if (outputCategory === 'intermediate') return
              // research_notes are already captured via write_file artifacts — skip to avoid duplicates
              if (outputCategory === 'final_report' || !outputCategory) {
                buffer.reportContent = content
              }
            },

            onComplete: () => {
              commitToStore()
              resolve()
            },

            onError: (err) => {
              console.error('Stream error while loading job data:', err)
              commitToStore()
              reject(err)
            },

            onDisconnect: () => {
              commitToStore()
              resolve()
            },
          },
        })

        clientRef.current = client
        client.connect()
      })
    },
    [idToken, setCurrentStatus]
  )

  /**
   * Main function to load job data
   * Checks ephemeral cache first - if data exists, just opens the panel
   * Otherwise fetches from backend
   */
  const loadJobData = useCallback(
    async (jobId: string, options: LoadJobDataOptions = {}): Promise<void> => {
      const { streamFullJob: shouldStreamFull = false } = options

      // Check ephemeral cache first - if we have data for this job, just show it
      const currentState = useChatStore.getState()
      const hasReportData =
        currentState.deepResearchJobId === jobId &&
        currentState.reportContent &&
        currentState.reportContent.trim().length > 0

      // For stream requests, also check if stream is already loaded
      const hasStreamData =
        currentState.deepResearchJobId === jobId &&
        currentState.deepResearchStreamLoaded

      // If we have what we need, just open the panel
      if (hasReportData && (!shouldStreamFull || hasStreamData)) {
        setResearchPanelTab('report')
        openRightPanel('research')
        return
      }

      setIsLoading(true)
      setError(null)

      try {
        const statusResponse = await getJobStatus(jobId, idToken || undefined)
        const jobStatus = statusResponse.status

        if (
          jobStatus !== 'success' &&
          jobStatus !== 'failure' &&
          jobStatus !== 'interrupted'
        ) {
          throw new Error(`Job is still ${jobStatus}. Cannot load data from incomplete job.`)
        }

        clearDeepResearch()

        if (shouldStreamFull) {
          await streamFullJob(jobId)
          setStreamLoaded(true)
        } else {
          await loadJobDataFast(jobId)
        }

        // Defensive cleanup: loaded data may have stale 'running' items
        // if the backend never sent completion events. Only treat as
        // successful for success jobs; interrupted/failed jobs should
        // leave un-attempted tasks as 'stopped'.
        stopAllDeepResearchSpinners(jobStatus === 'success')

        // Set job ID for cache tracking (so subsequent clicks show cached data)
        setLoadedJobId(jobId)

        setResearchPanelTab('report')
        openRightPanel('research')
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load job data'
        setError(errorMessage)
        console.error('Failed to load job data:', err)
        if (isUnavailableDeepResearchJobError(err)) {
          syncMissingJobToFailureState(jobId)
        }
        addErrorCard('agent.deep_research_load_failed', errorMessage)
        stopAllDeepResearchSpinners()
        completeDeepResearch()
        setStreaming(false)
      } finally {
        setIsLoading(false)
      }
    },
    [
      idToken,
      clearDeepResearch,
      loadJobDataFast,
      streamFullJob,
      setLoadedJobId,
      setStreamLoaded,
      stopAllDeepResearchSpinners,
      setResearchPanelTab,
      openRightPanel,
      addErrorCard,
      completeDeepResearch,
      setStreaming,
      syncMissingJobToFailureState,
    ]
  )

  /**
   * Public method: Load report + state via REST APIs (fast)
   */
  const loadReport = useCallback(
    async (jobId: string): Promise<void> => {
      await loadJobData(jobId, { streamFullJob: false })
    },
    [loadJobData]
  )

  /**
   * Public method: Import full job stream (slow but comprehensive)
   * Opens report tab after completion
   */
  const importJobStream = useCallback(
    async (jobId: string): Promise<void> => {
      await loadJobData(jobId, { streamFullJob: true })
    },
    [loadJobData]
  )

  /**
   * Import stream data only - does NOT change panel tab
   * Use when loading stream data for an already-open tab (e.g., Tasks/Thinking/Citations)
   * Checks ephemeral cache first to avoid duplicate API calls
   * Silently returns if job is still in progress (active SSE will populate data)
   */
  const importStreamOnly = useCallback(
    async (jobId: string): Promise<void> => {
      // Check if stream is already loaded for this job
      const currentState = useChatStore.getState()
      if (
        currentState.deepResearchJobId === jobId &&
        currentState.deepResearchStreamLoaded
      ) {
        return
      }

      setIsLoading(true)
      setError(null)

      try {
        const statusResponse = await getJobStatus(jobId, idToken || undefined)
        const jobStatus = statusResponse.status

        if (
          jobStatus !== 'success' &&
          jobStatus !== 'failure' &&
          jobStatus !== 'interrupted'
        ) {
          // Job is still in progress - silently return (live SSE will populate data)
          // This is expected when opening tabs for active jobs
          console.log(`[importStreamOnly] Job ${jobId} is still ${jobStatus}, skipping archive load`)
          setIsLoading(false)
          return
        }

        clearDeepResearch()
        await streamFullJob(jobId)
        // Defensive cleanup: loaded data may have stale 'running' items.
        // Only mark as successful completion for success jobs; interrupted/failed
        // jobs should leave un-attempted tasks as 'stopped'.
        stopAllDeepResearchSpinners(jobStatus === 'success')
        setStreamLoaded(true)
        setLoadedJobId(jobId)
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load stream data'
        setError(errorMessage)
        console.error('Failed to load stream data:', err)
        if (isUnavailableDeepResearchJobError(err)) {
          syncMissingJobToFailureState(jobId)
        }
        addErrorCard('agent.deep_research_load_failed', errorMessage)
        stopAllDeepResearchSpinners()
        completeDeepResearch()
        setStreaming(false)
      } finally {
        setIsLoading(false)
      }
    },
    [idToken, clearDeepResearch, streamFullJob, stopAllDeepResearchSpinners, setStreamLoaded, setLoadedJobId, syncMissingJobToFailureState, addErrorCard, completeDeepResearch, setStreaming]
  )

  return {
    loadReport,
    importJobStream,
    importStreamOnly,
    loadJobData,
    isLoading,
    error,
    clearError,
  }
}
