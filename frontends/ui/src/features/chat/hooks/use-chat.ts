// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useChat Hook
 *
 * Custom hook for managing chat interactions with the backend API.
 * Handles sending messages, streaming responses, and abort control.
 *
 * Now uses the /generate/stream endpoint which routes:
 * - intermediate steps -> Details Panel (Thinking tab)
 * - status updates -> Chat Area (status cards)
 * - prompts -> Chat Area (agent prompts)
 * - final report -> Details Panel (Report tab)
 */

'use client'

import { useCallback, useRef, useEffect } from 'react'
import { streamGenerate } from '@/adapters/api/chat-client'
import { useChatStore } from '../store'
import { useAuth } from '@/adapters/auth'
import type { Conversation, StatusType, ThinkingStep, PendingInteraction } from '../types'

interface UseChatReturn {
  /** Send a message and stream the response */
  sendMessage: (content: string) => Promise<void>
  /** Respond to a pending interaction (no-op for SSE mode, used for interface parity) */
  respondToInteraction: (response: string) => void
  /** Whether a message is currently streaming */
  isStreaming: boolean
  /** Whether we're waiting for the first token */
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
  /** Pending interaction requiring user response (always null for SSE mode) */
  pendingInteraction: PendingInteraction | null
}

/**
 * Hook for managing chat with streaming API
 *
 * Uses /generate/stream endpoint which provides:
 * - status: Agent activity updates (thinking, searching, planning, etc.)
 * - intermediate: Thinking steps for Details Panel
 * - prompt: Agent questions requiring user response
 * - report: Final report content for Details Panel
 */
export const useChat = (): UseChatReturn => {
  // Abort controller for cancelling requests
  const abortControllerRef = useRef<AbortController | null>(null)

  // Auth hook for getting user and token
  // Note: idToken is used for backend auth, not accessToken
  const { user, idToken } = useAuth()

  // Ref to track the current thinking step ID for appending content
  const currentThinkingStepIdRef = useRef<string | null>(null)
  // Ref to track the current status for detecting status changes
  const currentStatusRef = useRef<StatusType | null>(null)
  // Ref to store the final report content for adding to chat on completion
  const finalReportContentRef = useRef<string | null>(null)

  // Chat store
  const {
    currentConversation,
    isStreaming,
    isLoading,
    thinkingSteps,
    reportContent,
    currentStatus,
    addUserMessage,
    addThinkingStep,
    appendToThinkingStep,
    completeThinkingStep,
    setReportContent,
    addStatusCard,
    addAgentPrompt,
    addAgentResponse,
    addErrorCard,
    setCurrentStatus,
    setLoading,
    setStreaming,
    clearThinkingSteps,
    clearReportContent,
    createConversation: storeCreateConversation,
    setCurrentUser,
    getUserConversations,
    selectConversation: storeSelectConversation,
  } = useChatStore()

  // Sync authenticated user ID to store when auth state changes
  useEffect(() => {
    const userId = user?.id ?? null
    setCurrentUser(userId)
  }, [user?.id, setCurrentUser])

  /**
   * Send a message and stream the response via /generate/stream
   * Routes content to appropriate UI elements:
   * - status -> Chat Area status cards + new thinking step
   * - intermediate -> Details Panel Thinking tab (appends to current step)
   * - prompt -> Chat Area agent prompts
   * - report -> Details Panel Report tab
   */
  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim()) return

      // Create abort controller for this request
      abortControllerRef.current = new AbortController()

      // Reset tracking refs
      currentThinkingStepIdRef.current = null
      currentStatusRef.current = null
      finalReportContentRef.current = null

      try {
        // Add user message to store
        addUserMessage(content)

        // Clear previous thinking/report content for new request
        clearThinkingSteps()
        clearReportContent()

        // Get conversation after adding user message
        const conversation = useChatStore.getState().currentConversation
        if (!conversation) {
          throw new Error('No active conversation')
        }

        // Set initial status and create first thinking step
        setCurrentStatus('thinking')
        const initialStepId = addThinkingStep({
          category: 'tasks',
          functionName: '<workflow>',
          displayName: 'Workflow',
          content: 'Starting...',
          isComplete: false,
        })
        currentThinkingStepIdRef.current = initialStepId
        currentStatusRef.current = 'thinking'

        setStreaming(true)
        setLoading(false)

        // Stream the response using /generate/stream
        await streamGenerate(
          {
            inputMessage: content,
            sessionId: conversation.id,
            signal: abortControllerRef.current.signal,
            authToken: idToken,
          },
          {
            // Route thinking/intermediate content to Details Panel
            onThinking: (thinkingText) => {
              // Append to current thinking step
              if (currentThinkingStepIdRef.current) {
                appendToThinkingStep(currentThinkingStepIdRef.current, thinkingText)
              }
            },

            // Route status updates to Chat Area as status cards
            onStatus: (statusType, message) => {
              // If status changed, complete the previous step and start a new one
              if (statusType !== currentStatusRef.current) {
                // Complete the previous step if exists
                if (currentThinkingStepIdRef.current) {
                  completeThinkingStep(currentThinkingStepIdRef.current)
                }

                // Create new thinking step for new status
                const newStepId = addThinkingStep({
                  category: 'tasks',
                  functionName: `<${statusType}>`,
                  displayName: statusType.charAt(0).toUpperCase() + statusType.slice(1),
                  content: '',
                  isComplete: false,
                })
                currentThinkingStepIdRef.current = newStepId
                currentStatusRef.current = statusType
              }

              setCurrentStatus(statusType)
              addStatusCard(statusType, message)
            },

            // Route prompts to Chat Area for user response
            onPrompt: (promptType, promptContent, promptOptions, placeholder) => {
              addAgentPrompt(promptType, promptContent, promptOptions, placeholder)
              // Pause streaming while waiting for user response
              setStreaming(false)
            },

            // Route final report to Details Panel and store for chat
            onReport: (reportText) => {
              setReportContent(reportText)
              finalReportContentRef.current = reportText
            },

            // Handle completion
            onComplete: () => {
              // Complete the final thinking step
              if (currentThinkingStepIdRef.current) {
                completeThinkingStep(currentThinkingStepIdRef.current)
              }
              currentThinkingStepIdRef.current = null
              currentStatusRef.current = null

              // Add completion message to ChatArea with "View Report" button if there's a report
              const hasReport = !!finalReportContentRef.current
              addAgentResponse('Research complete.', hasReport)
              finalReportContentRef.current = null

              setStreaming(false)
              setCurrentStatus('complete')
              addStatusCard('complete', 'Research complete')
              abortControllerRef.current = null
            },

            // Handle errors
            onError: (err) => {
              // Complete the current thinking step on error
              if (currentThinkingStepIdRef.current) {
                completeThinkingStep(currentThinkingStepIdRef.current)
              }
              currentThinkingStepIdRef.current = null
              currentStatusRef.current = null

              addErrorCard('agent.response_failed', err.message)
              setCurrentStatus(null)
              setStreaming(false)
              setLoading(false)
              abortControllerRef.current = null
            },
          }
        )
      } catch (err) {
        // Complete thinking step on exception
        if (currentThinkingStepIdRef.current) {
          completeThinkingStep(currentThinkingStepIdRef.current)
        }
        currentThinkingStepIdRef.current = null
        currentStatusRef.current = null

        if (err instanceof Error && err.name !== 'AbortError') {
          addErrorCard('agent.response_failed', err.message)
          setCurrentStatus(null)
        }
        setStreaming(false)
        abortControllerRef.current = null
      }
    },
    [
      addUserMessage,
      addThinkingStep,
      appendToThinkingStep,
      completeThinkingStep,
      setReportContent,
      addStatusCard,
      addAgentPrompt,
      addAgentResponse,
      addErrorCard,
      setCurrentStatus,
      setLoading,
      setStreaming,
      clearThinkingSteps,
      clearReportContent,
      idToken,
    ]
  )

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

  /**
   * Respond to a pending interaction (no-op for SSE mode)
   * SSE mode doesn't support HITL - use WebSocket mode for that.
   * This is provided for interface parity with useWebSocketChat.
   */
  const respondToInteraction = useCallback((_response: string) => {
    console.warn(
      'respondToInteraction called in SSE mode - HITL not supported. Use WebSocket mode.'
    )
  }, [])

  // Get user's filtered conversations
  const userConversations = getUserConversations()

  return {
    sendMessage,
    respondToInteraction,
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
    pendingInteraction: null, // SSE mode doesn't support HITL
  }
}
