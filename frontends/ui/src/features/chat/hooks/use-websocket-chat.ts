// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useWebSocketChat Hook
 *
 * Custom hook for managing chat interactions via WebSocket.
 * Uses NAT WebSocket protocol for full HITL (human-in-the-loop) support.
 *
 * Routes messages to appropriate UI elements:
 * - system_response -> Chat Area (agent_response)
 * - system_intermediate -> Details Panel (Thinking tab)
 * - system_interaction -> Chat Area (AgentPrompt for user response)
 * - error -> Error handling
 *
 * Note: Research Panel (reportContent) is only populated by deep research
 * SSE events via use-deep-research.ts, not by WebSocket responses.
 */

'use client'

import { useCallback, useRef, useEffect, useState } from 'react'
import {
  NATWebSocketClient,
  createNATWebSocketClient,
  type NATWebSocketClientCallbacks,
  type ConnectionChangeContext,
  type NATHumanPrompt,
  type NATIntermediateStepContent,
  type NATErrorContent,
  HumanPromptType,
} from '@/adapters/api/websocket-client'
import { checkBackendHealthCached, invalidateHealthCache } from '@/shared/hooks/use-backend-health'
import { useChatStore } from '../store'
import { useConnectionRecovery } from './use-connection-recovery'
import { useLayoutStore } from '@/features/layout/store'
import { WEB_SEARCH_SOURCE_ID } from '@/features/layout/data-sources'
import { useDocumentsStore } from '@/features/documents/store'
import { useAuth } from '@/adapters/auth'
import type {
  Conversation,
  PromptType,
  PendingInteraction,
  StatusType,
  ThinkingStep,
  ErrorCode,
} from '../types'
import {
  parseFunctionName,
  mapFunctionToCategory,
  getDisplayName,
  getWorkflowDisplayName,
  isFunctionStepName,
  formatPayload,
} from '../lib/intermediate-step-parser'

/**
 * Map NAT/backend error codes to frontend ErrorCode for consistent UI display.
 * This provides a generic mapping for any backend error.
 */
const mapNATErrorToErrorCode = (natErrorCode: string): ErrorCode => {
  // Map known NAT error types
  switch (natErrorCode) {
    case 'invalid_message':
    case 'invalid_message_type':
    case 'invalid_user_message_content':
    case 'invalid_data_content':
      return 'agent.response_failed'
    case 'CONNECTION_FAILED':
      return 'connection.failed'
    case 'unknown_error':
    default:
      return 'system.unknown'
  }
}

interface UseWebSocketChatOptions {
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean
}

interface UseWebSocketChatReturn {
  /** Send a message via WebSocket */
  sendMessage: (content: string) => void
  /** Respond to a pending interaction (clarification, approval, etc.) */
  respondToInteraction: (response: string) => void
  /** Disconnect from the WebSocket server */
  disconnect: () => void
  /** Reconnect the WebSocket */
  connect: () => void
  /** Whether WebSocket is connected */
  isConnected: boolean
  /** Whether a response is currently being received */
  isStreaming: boolean
  /** Whether we're waiting for the first response */
  isLoading: boolean
  /** All messages in the current conversation */
  messages: Conversation['messages'] | undefined
  /** Current conversation */
  conversation: Conversation | null
  /** Create a new conversation */
  createConversation: () => void
  /** Conversations filtered by current user */
  userConversations: Conversation[]
  /** Select a conversation by ID */
  selectConversation: (conversationId: string) => void
  /** Thinking steps from Details Panel */
  thinkingSteps: ThinkingStep[]
  /** Report content from Details Panel */
  reportContent: string
  /** Current status type */
  currentStatus: StatusType | null
  /** Pending interaction requiring user response */
  pendingInteraction: PendingInteraction | null
}

/**
 * Map NAT human prompt types to our PromptType
 */
const mapHumanPromptType = (natType: string): PromptType => {
  switch (natType) {
    case HumanPromptType.TEXT:
      return 'text-input'
    case HumanPromptType.MULTIPLE_CHOICE:
      return 'choice'
    case HumanPromptType.BINARY_CHOICE:
      return 'approval'
    case HumanPromptType.APPROVAL:
      return 'approval'
    default:
      return 'clarification'
  }
}

/**
 * Hook for managing chat with WebSocket connection
 *
 * Uses NAT WebSocket protocol for bidirectional communication,
 * enabling full HITL support including clarification prompts
 * and approval flows.
 */
export const useWebSocketChat = (options: UseWebSocketChatOptions = {}): UseWebSocketChatReturn => {
  const { autoConnect = true } = options

  // WebSocket client ref
  const wsClientRef = useRef<NATWebSocketClient | null>(null)

  // Connection state
  const [isConnected, setIsConnected] = useState(false)

  // Ref to track the current thinking step ID for appending content
  const currentThinkingStepIdRef = useRef<string | null>(null)
  // Ref to track the current status for detecting status changes
  const currentStatusRef = useRef<StatusType | null>(null)

  // Auth hook for getting user and token
  // Note: idToken is used for backend auth, not accessToken
  const { user, idToken } = useAuth()

  // Chat store
  const {
    currentConversation,
    isStreaming,
    isLoading,
    thinkingSteps,
    reportContent,
    currentStatus,
    pendingInteraction,
    addUserMessage,
    addAgentResponse,
    addAgentResponseWithMeta,
    addThinkingStep,
    appendToThinkingStep,
    completeThinkingStep,
    updateThinkingStepByFunctionName,
    findThinkingStepByFunctionName,
    addAgentPrompt,
    addErrorCard,
    dismissConnectionErrors,
    setCurrentStatus,
    setPendingInteraction,
    clearPendingInteraction,
    setLoading,
    setStreaming,
    clearReportContent,
    createConversation: storeCreateConversation,
    setCurrentUser,
    getUserConversations,
    selectConversation: storeSelectConversation,
    respondToPrompt,
    // Deep research SSE
    startDeepResearch,
    // Deep research banners
    addDeepResearchBanner,
    // Plan messages for PlanTab
    addPlanMessage,
    updatePlanMessageResponse,
    // Conversation management
    updateConversationTitle,
  } = useChatStore()

  // Sync authenticated user ID to store when auth state changes
  useEffect(() => {
    const userId = user?.id ?? null
    setCurrentUser(userId)
  }, [user?.id, setCurrentUser])

  /**
   * Create WebSocket callbacks that route messages to the store
   */
  const createCallbacks = useCallback((): NATWebSocketClientCallbacks => {
    /**
     * Guard against stale messages from a previous (cancelled) workflow.
     * Returns true when the message should be dropped.
     */
    const isStaleMessage = (parentId?: string): boolean => {
      const activeId = wsClientRef.current?.activeParentId
      if (!parentId || !activeId) return false
      return parentId !== activeId
    }

    return {
      onResponse: (content: string, status: string, isFinal: boolean, parentId?: string) => {
        if (isStaleMessage(parentId)) {
          console.warn('Dropping stale system_response (parent_id mismatch)', { parentId, active: wsClientRef.current?.activeParentId })
          return
        }

        // Check for deep research escalation signal
        // Backend sends: "Deep research job submitted. Job ID: {uuid}"
        const deepResearchMatch = content?.match(
          /Deep research job submitted\. Job ID: ([a-f0-9-]+)/i
        )

        if (deepResearchMatch) {
          const jobId = deepResearchMatch[1]
          // Get current state for plan messages and conversation
          const state = useChatStore.getState()
          const currentPlanMessages = state.planMessages
          const currentConversation = state.currentConversation
          
          // Extract research title from plan messages for conversation title
          // Try multiple sources: plan preview, any plan message, or original user query
          if (currentConversation) {
            let extractedTitle: string | null = null
            
            // First, look at all plan messages for a title
            for (const planMsg of currentPlanMessages) {
              if (extractedTitle) break
              
              // Pattern 1: JSON report_title field
              const jsonTitleMatch = planMsg.text.match(/"report_title":\s*"([^"]+)"/i)
              if (jsonTitleMatch) {
                extractedTitle = jsonTitleMatch[1]
                break
              }
              
              // Pattern 2: Markdown Report Title heading
              const reportTitleMatch = planMsg.text.match(/\*\*Report Title[:\s]*\*\*\s*\n?\s*\*?([^*\n]+)/i)
                || planMsg.text.match(/Report Title[:\s]*\n?\s*\*?([^*\n]+)/i)
              if (reportTitleMatch) {
                extractedTitle = reportTitleMatch[1].trim()
                break
              }
              
              // Pattern 3: First markdown heading
              const mdHeadingMatch = planMsg.text.match(/^#+\s+(.+?)(?:\n|$)/m)
              if (mdHeadingMatch) {
                extractedTitle = mdHeadingMatch[1].trim()
                break
              }
            }
            
            // Fallback: Use the last user message if no title found in plan
            if (!extractedTitle) {
              const userMessages = currentConversation.messages.filter((m) => m.role === 'user')
              const lastUserMsg = userMessages[userMessages.length - 1]
              // Use the last user message if it's not a simple greeting
              if (lastUserMsg && lastUserMsg.content.length > 10) {
                extractedTitle = lastUserMsg.content
              }
            }
            
            if (extractedTitle) {
              // Clean up the title
              const cleanTitle = extractedTitle
                .replace(/^\*+|\*+$/g, '') // Remove asterisks
                .replace(/^["']|["']$/g, '') // Remove quotes
                .trim()
              
              // Truncate to reasonable length
              const title = cleanTitle.length > 80 
                ? cleanTitle.substring(0, 77) + '...' 
                : cleanTitle
              
              if (title.length > 0) {
                updateConversationTitle(currentConversation.id, title)
              }
            }
          }
          
          // Add 'starting' banner as a persistent message
          addDeepResearchBanner('starting', jobId)
          
          // Create tracking message with empty content (won't render due to content guard)
          // This message carries job metadata for session restoration
          const messageId = addAgentResponseWithMeta(
            '', // Empty content - AgentResponse returns null for empty content
            false,
            {
              deepResearchJobId: jobId,
              deepResearchJobStatus: 'submitted',
              isDeepResearchActive: true,
              planMessages: currentPlanMessages.length > 0 ? [...currentPlanMessages] : undefined,
            }
          )
          // Start deep research SSE streaming bound to this message
          startDeepResearch(jobId, messageId)
          // Keep isStreaming=true to block input - deep research will release it on completion
          setLoading(false)
          // Don't add this as final response - let SSE handle the rest
          return
        }

        // Any system_response_message with text content should be added as AgentResponse immediately
        if (content && content.trim()) {
          // Add to chat area as AgentResponse
          // Note: reportContent is only set by deep research SSE events (use-deep-research.ts)
          addAgentResponse(content)
        }

        // status: "complete" with null text signals task completion
        if (isFinal) {
          // Guard: if we're not streaming, this is a stale COMPLETE from a
          // previous workflow that outlived its socket (e.g. after disconnect).
          const { isStreaming: currentlyStreaming } = useChatStore.getState()
          if (!currentlyStreaming) {
            console.warn('Ignoring stale isFinal -- not currently streaming')
            return
          }

          // Complete any pending thinking step
          if (currentThinkingStepIdRef.current) {
            completeThinkingStep(currentThinkingStepIdRef.current)
            currentThinkingStepIdRef.current = null
            currentStatusRef.current = null
          }

          // Stop streaming and mark complete
          setStreaming(false)
          setCurrentStatus('complete')

          // Clear any pending interaction (HITL prompt) on completion
          clearPendingInteraction()
        }
      },

      onIntermediateStep: (content: NATIntermediateStepContent | string, status: string, _parentId?: string) => {
        // NAT uses an internal step ID (not the user message ID) for intermediate step parent_id,
        // so we cannot use parent_id for stale detection here. Guard instead on isStreaming:
        // if we are not currently streaming, the workflow that sent this step was already
        // cancelled/disconnected, so discard it.
        const { isStreaming: currentlyStreaming } = useChatStore.getState()
        if (!currentlyStreaming) {
          console.warn('Ignoring stale intermediate step -- not currently streaming')
          return
        }
        // Handle string content (legacy format)
        if (typeof content === 'string') {
          // For plain string content, create a generic thinking step
          if (content && content.trim()) {
            const stepId = addThinkingStep({
              category: 'agents',
              functionName: 'unknown',
              displayName: 'Processing',
              content: content + '\n',
              isComplete: false,
            })
            currentThinkingStepIdRef.current = stepId
            currentStatusRef.current = 'thinking'
          }
          return
        }

        // Parse structured content with name and payload
        if (!content.name) return

        const { functionName, isComplete } = parseFunctionName(content.name)
        const category = mapFunctionToCategory(functionName)
        const workflowLabel = getWorkflowDisplayName(functionName)
        const displayName = workflowLabel || getDisplayName(functionName)
        const isTopLevel = isFunctionStepName(content.name)
        const formattedPayload = formatPayload(content.payload || '')

        // Check if we already have a step for this function
        const existingStep = findThinkingStepByFunctionName(functionName)

        if (isComplete && existingStep) {
          // Update existing step with complete status and final content
          updateThinkingStepByFunctionName(functionName, formattedPayload, true)
        } else if (existingStep) {
          // Append to existing step (shouldn't happen often, but handle gracefully)
          appendToThinkingStep(existingStep.id, '\n' + formattedPayload)
        } else {
          // Create new step for this function (or model/tool sub-call)
          const stepId = addThinkingStep({
            category,
            functionName,
            displayName,
            content: formattedPayload,
            rawPayload: content.payload,
            isComplete,
            isTopLevel,
          })
          currentThinkingStepIdRef.current = stepId
          currentStatusRef.current = 'thinking'
        }

        // Update status based on message status
        if (status === 'in_progress') {
          setCurrentStatus('thinking')
        }
      },

      onHumanPrompt: (promptId: string, parentId: string, prompt: NATHumanPrompt) => {
        // Store the pending interaction for the UI to handle
        const inputType = prompt.input_type as PendingInteraction['inputType']
        const interaction: PendingInteraction = {
          id: promptId,
          parentId,
          inputType,
          text: prompt.text,
          options: prompt.options,
          defaultValue: prompt.default_value,
        }
        setPendingInteraction(interaction)

        // Add to PlanTab FIRST so it's captured when saving prompt message
        addPlanMessage({
          text: prompt.text,
          inputType: prompt.input_type as 'text' | 'multiple_choice' | 'binary_choice' | 'approval' | 'notification',
        })

        // Add as an agent prompt in the chat with HITL routing info for persistence
        // This captures current planMessages (including the one just added) for session restoration
        const promptType = mapHumanPromptType(prompt.input_type)
        addAgentPrompt(promptType, prompt.text, prompt.options, undefined, promptId, parentId, inputType)

        // Pause streaming while waiting for user response
        setStreaming(false)
        setLoading(false)
      },

      onError: async (errorContent: NATErrorContent) => {
        // Connection errors (all retries exhausted) -- gate with health check
        if (errorContent.code === 'CONNECTION_FAILED') {
          const backendUp = await checkBackendHealthCached()
          if (backendUp) {
            // Backend is healthy -- this was a transient WebSocket issue.
            // Don't alarm the user; the connection will re-establish on next send.
            return
          }
          // Backend is truly down -- show error
          addErrorCard(
            'connection.failed',
            errorContent.message,
            errorContent.details,
          )
          setCurrentStatus(null)
          setStreaming(false)
          setLoading(false)
          clearPendingInteraction()
          return
        }

        // Application-level errors from the backend (agent errors, etc.)
        // Complete any pending thinking step on error
        if (currentThinkingStepIdRef.current) {
          completeThinkingStep(currentThinkingStepIdRef.current)
          currentThinkingStepIdRef.current = null
          currentStatusRef.current = null
        }

        // Map NAT error to frontend error code and display error card
        const errorCode = mapNATErrorToErrorCode(errorContent.code)
        addErrorCard(
          errorCode,
          errorContent.message,
          errorContent.details,
        )

        setCurrentStatus(null)
        setStreaming(false)
        setLoading(false)

        // Clear any pending interaction on error
        clearPendingInteraction()
      },

      onConnectionChange: (status, context?: ConnectionChangeContext) => {
        setIsConnected(status === 'connected')

        if (status === 'connected') {
          invalidateHealthCache()
          dismissConnectionErrors()
          return
        }

        // Intentional disconnects (session switch, cleanup): no error UI
        if (context?.intentional) return

        if (status === 'error' || status === 'disconnected') {
          // Don't show error cards here. The WebSocket client suppresses
          // intermediate statuses during reconnection, and fires onError
          // with CONNECTION_FAILED only after all retries are exhausted.
          // At that point the health-check gate decides whether to show UI.

          // Complete any in-progress thinking step so the UI doesn't hang
          if (currentThinkingStepIdRef.current) {
            completeThinkingStep(currentThinkingStepIdRef.current)
            currentThinkingStepIdRef.current = null
            currentStatusRef.current = null
          }

          // Reset streaming/loading state if connection dropped mid-request
          setStreaming(false)
          setLoading(false)
          clearPendingInteraction()
        }
      },
    }
  }, [
    addAgentResponse,
    addAgentResponseWithMeta,
    addThinkingStep,
    appendToThinkingStep,
    completeThinkingStep,
    updateThinkingStepByFunctionName,
    findThinkingStepByFunctionName,
    addAgentPrompt,
    addErrorCard,
    dismissConnectionErrors,
    setCurrentStatus,
    setPendingInteraction,
    clearPendingInteraction,
    setLoading,
    setStreaming,
    startDeepResearch,
    addDeepResearchBanner,
    addPlanMessage,
    updateConversationTitle,
  ])

  /**
   * Initialize WebSocket client when conversation changes
   */
  useEffect(() => {
    if (!currentConversation || !autoConnect) return

    // Create new client if needed
    if (!wsClientRef.current) {
      wsClientRef.current = createNATWebSocketClient({
        conversationId: currentConversation.id,
        callbacks: createCallbacks(),
        authToken: idToken,
      })
      wsClientRef.current.connect()
    } else {
      // Update conversation ID on existing client
      wsClientRef.current.updateConversationId(currentConversation.id)
    }

    // Cleanup on unmount
    return () => {
      if (wsClientRef.current) {
        wsClientRef.current.disconnect()
        wsClientRef.current = null
      }
    }
  }, [currentConversation?.id, autoConnect, idToken, createCallbacks])

  /**
   * Update auth token when it changes
   */
  useEffect(() => {
    if (wsClientRef.current && idToken) {
      wsClientRef.current.updateAuthToken(idToken)
    }
  }, [idToken])

  /**
   * Send a message via WebSocket
   */
  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim()) return

      // Collect metadata about data sources and files before adding user message
      const layoutState = useLayoutStore.getState()
      let enabledDataSources = layoutState.enabledDataSourceIds

      // Filter out authenticated sources if user doesn't have a valid idToken
      if (!idToken) {
        enabledDataSources = enabledDataSources.filter(
          (sourceId) => sourceId === WEB_SEARCH_SOURCE_ID
        )
      }

      // Get session files
      const sessionId = useChatStore.getState().currentConversation?.id
      const trackedFiles = useDocumentsStore.getState().trackedFiles
      const sessionFiles = sessionId
        ? trackedFiles.filter(
            (f) => f.collectionName === sessionId && (f.status === 'ingesting' || f.status === 'success')
          )
        : []

      const hasSessionFiles = sessionFiles.length > 0

      // Add knowledge_layer to data sources if files exist
      const dataSourcesForMessage = hasSessionFiles && layoutState.knowledgeLayerAvailable
        ? [...enabledDataSources, 'knowledge_layer']
        : enabledDataSources

      // Prepare file metadata for display
      const messageFiles = sessionFiles.map((f) => ({
        id: f.id,
        fileName: f.fileName,
      }))

      // Add user message to store with metadata
      addUserMessage(content, {
        enabledDataSources: dataSourcesForMessage,
        messageFiles,
      })

      // Get the conversation ID from store (may have been created by addUserMessage)
      const storeState = useChatStore.getState()
      const conversationId = storeState.currentConversation?.id

      // Clear report content and pending interaction for new request
      // Note: We do NOT clear thinkingSteps - they persist per userMessageId for chat history
      clearReportContent()
      clearPendingInteraction()

      // Reset tracking refs
      currentThinkingStepIdRef.current = null
      currentStatusRef.current = null

      // Set initial status; first real step will be "Workflow: Chat Researcher" from backend
      setCurrentStatus('thinking')
      setStreaming(true)
      setLoading(true)

      // Helper to actually send the message
      const doSend = () => {
        if (wsClientRef.current?.isConnected()) {
          wsClientRef.current.sendMessage(content, dataSourcesForMessage)
          setLoading(false)
        } else {
          addErrorCard('connection.failed', 'WebSocket connection failed')
          setStreaming(false)
          setLoading(false)
        }
      }

      // If WebSocket client exists and is connected, send immediately
      if (wsClientRef.current?.isConnected()) {
        doSend()
      } else if (conversationId) {
        // WebSocket not ready but we have a conversation - initialize synchronously
        // Create callbacks that include the send-on-connect logic
        const callbacks = createCallbacks()
        const originalOnConnectionChange = callbacks.onConnectionChange
        callbacks.onConnectionChange = (status, ctx) => {
          originalOnConnectionChange?.(status, ctx)
          if (status === 'connected') {
            doSend()
          }
        }

        // Create and connect the WebSocket client
        wsClientRef.current = createNATWebSocketClient({
          conversationId,
          callbacks,
          authToken: idToken,
        })
        wsClientRef.current.connect()
      } else {
        // No conversation ID - shouldn't happen but handle gracefully
        addErrorCard('system.unknown', 'No active conversation')
        setStreaming(false)
        setLoading(false)
      }
    },
    [
      addUserMessage,
      addThinkingStep,
      addErrorCard,
      clearReportContent,
      clearPendingInteraction,
      setCurrentStatus,
      setStreaming,
      setLoading,
      idToken,
      createCallbacks,
    ]
  )

  /**
   * Respond to a pending interaction (clarification, approval, etc.)
   */
  const respondToInteraction = useCallback(
    (response: string) => {
      if (!pendingInteraction) {
        console.warn('No pending interaction to respond to')
        return
      }

      // Update prompt in store
      // Find the last prompt message and mark it as responded
      const messages = currentConversation?.messages ?? []
      const lastPrompt = [...messages]
        .reverse()
        .find((m) => m.messageType === 'prompt' && !m.isPromptResponded)
      if (lastPrompt) {
        respondToPrompt(lastPrompt.id, response)
      }

      // Update the last plan message with the user response
      const currentPlanMessages = useChatStore.getState().planMessages
      if (currentPlanMessages.length > 0) {
        const lastPlanMessage = currentPlanMessages[currentPlanMessages.length - 1]
        if (!lastPlanMessage.userResponse) {
          updatePlanMessageResponse(lastPlanMessage.id, response)
        }
      }

      // Send response via WebSocket
      if (wsClientRef.current?.isConnected()) {
        wsClientRef.current.sendInteractionResponse(
          pendingInteraction.id,
          pendingInteraction.parentId,
          response
        )
        // Resume streaming
        setStreaming(true)
        setLoading(true)
      } else {
        addErrorCard('connection.failed', 'WebSocket not connected')
      }
    },
    [
      pendingInteraction,
      currentConversation?.messages,
      respondToPrompt,
      updatePlanMessageResponse,
      addErrorCard,
      setStreaming,
      setLoading,
    ]
  )

  /**
   * Connect to WebSocket
   */
  const connect = useCallback(() => {
    if (wsClientRef.current) {
      wsClientRef.current.connect()
    } else if (currentConversation) {
      wsClientRef.current = createNATWebSocketClient({
        conversationId: currentConversation.id,
        callbacks: createCallbacks(),
        authToken: idToken,
      })
      wsClientRef.current.connect()
    }
  }, [currentConversation, idToken, createCallbacks])

  // Activate recovery polling when connection error cards are visible
  useConnectionRecovery(connect)

  /**
   * Disconnect from WebSocket
   */
  const disconnect = useCallback(() => {
    if (wsClientRef.current) {
      wsClientRef.current.disconnect()
    }
    setStreaming(false)
    setLoading(false)
  }, [setStreaming, setLoading])

  /**
   * Create a new conversation
   */
  const createConversation = useCallback(() => {
    storeCreateConversation()
  }, [storeCreateConversation])

  /**
   * Select a conversation by ID
   */
  const selectConversation = useCallback(
    (conversationId: string) => {
      storeSelectConversation(conversationId)
    },
    [storeSelectConversation]
  )

  // Get user's filtered conversations
  const userConversations = getUserConversations()

  return {
    sendMessage,
    respondToInteraction,
    disconnect,
    connect,
    isConnected,
    isStreaming,
    isLoading,
    messages: currentConversation?.messages ?? [],
    conversation: currentConversation,
    createConversation,
    userConversations,
    selectConversation,
    thinkingSteps,
    reportContent,
    currentStatus,
    pendingInteraction,
  }
}
