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

import { useCallback, useRef, useEffect, useState, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { getSession } from 'next-auth/react'
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
import { useDocumentsStore } from '@/features/documents/store'
import { useAuth } from '@/adapters/auth'
import { isLikelyAuthRelatedTransportError } from '../lib/transport-auth-signals'
import type {
  ChatMessage,
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

const EMPTY_MESSAGES: ChatMessage[] = []
const EMPTY_CONVERSATIONS: Conversation[] = []

/**
 * Buffer entry for an outgoing payload that has to bridge a socket
 * rotation. Discriminated by `kind` because both chat messages and HITL
 * interaction responses can hit `auth_expired` at the backend, and the
 * drain on the freshly-handshaken socket has to dispatch back to the
 * right `NATWebSocketClient` method.
 */
type PendingOutgoing =
  | { kind: 'message'; content: string; dataSources: string[] }
  | { kind: 'interaction'; interactionId: string; parentId: string; response: string }

/**
 * Seconds before token expiry to proactively rotate the WebSocket. The
 * backend only validates the JWT at the WS upgrade, so an open socket
 * keeps trusting an expired token until we close + reopen it.
 *
 * If the timer fires mid-stream, rotation is deferred until `isStreaming`
 * returns to false so long-running responses are never cut short.
 *
 * INVARIANT: must be smaller than the server's `TOKEN_REFRESH_BUFFER_SECONDS`
 * (default 15min) so NextAuth has already rotated the JWT by the time we
 * upgrade with a fresh cookie.
 */
const WS_REFRESH_SOFT_GUARD_SECONDS = 60

/**
 * Hard cap on consecutive `auth_expired` rotations before we surface a
 * `session_expired` banner instead of silently rotating again.
 *
 * Why a cap is necessary: each `auth_expired` response from the backend
 * goes through `rotate()`, which resets `reconnectCount` to 0. That means
 * the WS client's own retry safety net (CONNECTION_FAILED after N
 * exhausted reconnect attempts) never trips on the auth_expired path --
 * the counter is wiped on every rotation. Without an upper bound here,
 * a stale-NextAuth-cache or clock-skew condition where `getSession()`
 * keeps handing us the same already-expired JWT can produce dozens of
 * silent rotations per minute (one per `auth_expired` round-trip) until
 * the refresh-token itself expires. That's invisible to the user (just a
 * spinner that never stops), wasteful for server connection slots, and
 * indistinguishable from a DDoS at the rate-limit layer.
 *
 * 1 is normal (the whole point of the silent reconnect path). 2 is the
 * documented preflight-then-second-auth_expired chain (we have a test).
 * >= 4 is a loop -- bail out, clear buffers, ask the user to sign in
 * again. Counter is reset on any successful response/intermediate step
 * because a single passing message proves the post-rotation auth is alive.
 */
const MAX_CONSECUTIVE_AUTH_EXPIRED = 3

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

  /**
   * Single-slot buffer for an outgoing payload deferred by a socket
   * rotation (stale token pre-flight or `auth_expired` from backend).
   * Drained inside `onConnectionChange('connected')`. Single-slot is
   * sufficient because `setStreaming(true)` gates new sends during rotation.
   *
   * Tagged by `kind` because the drain has to dispatch back to either
   * `sendMessage` (chat) or `sendInteractionResponse` (HITL). The backend
   * applies the same per-message JWT expiry gate to both; without the kind
   * tag a HITL response sent right after token expiry would either be
   * dropped (no buffer) or wrongly replayed as the previous chat message.
   */
  const pendingOutgoingRef = useRef<PendingOutgoing | null>(null)

  /**
   * Last payload written to the socket, kept until the workflow completes
   * or hits a non-auth error. Lets us auto-resend on `auth_expired` without
   * losing the user's payload. Distinct from `pendingOutgoingRef` so a
   * routine soft rotation doesn't replay an already-completed payload.
   */
  const lastSentOutgoingRef = useRef<PendingOutgoing | null>(null)

  /**
   * Set by the soft timer when it fires while streaming; consumed by the
   * deferred-rotation effect once `isStreaming` returns to false. Ref (not
   * state) so flipping the flag doesn't re-run the timer effect.
   */
  const pendingRotationRef = useRef(false)

  /**
   * Consecutive `auth_expired` rotations without a successful response in
   * between. Incremented in `onError(auth_expired)`, reset to 0 by any
   * `onResponse` / `onIntermediateStep` (a passing message proves auth is
   * alive on the rotated socket). When it exceeds
   * `MAX_CONSECUTIVE_AUTH_EXPIRED` we stop silently rotating and surface
   * `auth.session_expired` so the user can re-sign-in. See the docstring
   * on `MAX_CONSECUTIVE_AUTH_EXPIRED` for why this safety net is required.
   */
  const consecutiveAuthExpiredRef = useRef(0)

  /**
   * Single rotation primitive. Delegates to `client.rotate()` -- an atomic
   * client-side swap that detaches handlers from the old socket before
   * closing it, eliminating the `onclose` race where a late close from
   * the rotated-out socket would be misclassified as an unintentional
   * disconnect on the freshly-opened one.
   *
   * `client.connect()` (invoked inside `rotate()`) runs `onBeforeReconnect`,
   * which is the only call site for `getSession()` -- routing all refreshes
   * through one path avoids racing the SessionProvider polling (which
   * would cause `invalid_grant` with rotating refresh tokens).
   */
  const rotateSocket = useCallback((reason: string): void => {
    const client = wsClientRef.current
    if (!client) return
    console.warn(`[WS] Rotating connection before token expiry (${reason})`)
    void client.rotate()
  }, [])

  const { user, authRequired, error: authError } = useAuth()

  /**
   * Token expiry (seconds since epoch) that authenticates the *current*
   * socket. Captured from the `getSession()` call that primes the cookie
   * for the upcoming upgrade. Intentionally decoupled from the live
   * `useAuth().idTokenExpiresAt`: SessionProvider polling advances the
   * live value but does NOT re-authenticate an already-open socket, so
   * binding the timer to it would let polling clear it before it fires.
   */
  const [activeSocketTokenExpiresAt, setActiveSocketTokenExpiresAt] =
    useState<number | undefined>(undefined)

  /**
   * Refresh the NextAuth session before opening a new WebSocket so the
   * upgrade request carries an up-to-date idToken cookie, and anchor the
   * rotation deadline to the expiry returned by that same call.
   */
  const refreshAuthBeforeReconnect = useCallback(async (): Promise<void> => {
    if (!authRequired) return
    try {
      const session = await getSession()
      if (session?.idTokenExpiresAt) {
        setActiveSocketTokenExpiresAt(session.idTokenExpiresAt)
      }
    } catch (err) {
      console.warn('[useWebSocketChat] getSession before WS reconnect failed', err)
    }
  }, [authRequired])

  // Chat store — reactive state only
  const {
    currentConversation,
    conversations,
    currentUserId,
    isStreaming,
    isLoading,
    thinkingSteps,
    reportContent,
    currentStatus,
    pendingInteraction,
  } = useChatStore(useShallow((s) => ({
    currentConversation: s.currentConversation,
    conversations: s.conversations,
    currentUserId: s.currentUserId,
    isStreaming: s.isStreaming,
    isLoading: s.isLoading,
    thinkingSteps: s.thinkingSteps,
    reportContent: s.reportContent,
    currentStatus: s.currentStatus,
    pendingInteraction: s.pendingInteraction,
  })))

  // Actions — stable references, individual selectors won't cause re-renders
  const addUserMessage = useChatStore((s) => s.addUserMessage)
  const addAgentResponse = useChatStore((s) => s.addAgentResponse)
  const addAgentResponseWithMeta = useChatStore((s) => s.addAgentResponseWithMeta)
  const addThinkingStep = useChatStore((s) => s.addThinkingStep)
  const appendToThinkingStep = useChatStore((s) => s.appendToThinkingStep)
  const completeThinkingStep = useChatStore((s) => s.completeThinkingStep)
  const updateThinkingStepByFunctionName = useChatStore((s) => s.updateThinkingStepByFunctionName)
  const findThinkingStepByFunctionName = useChatStore((s) => s.findThinkingStepByFunctionName)
  const addAgentPrompt = useChatStore((s) => s.addAgentPrompt)
  const addErrorCard = useChatStore((s) => s.addErrorCard)
  const dismissConnectionErrors = useChatStore((s) => s.dismissConnectionErrors)
  const setCurrentStatus = useChatStore((s) => s.setCurrentStatus)
  const setPendingInteraction = useChatStore((s) => s.setPendingInteraction)
  const clearPendingInteraction = useChatStore((s) => s.clearPendingInteraction)
  const setLoading = useChatStore((s) => s.setLoading)
  const setStreaming = useChatStore((s) => s.setStreaming)
  const clearReportContent = useChatStore((s) => s.clearReportContent)
  const storeCreateConversation = useChatStore((s) => s.createConversation)
  const setCurrentUser = useChatStore((s) => s.setCurrentUser)
  const storeSelectConversation = useChatStore((s) => s.selectConversation)
  const respondToPrompt = useChatStore((s) => s.respondToPrompt)
  const startDeepResearch = useChatStore((s) => s.startDeepResearch)
  const addDeepResearchBanner = useChatStore((s) => s.addDeepResearchBanner)
  const addPlanMessage = useChatStore((s) => s.addPlanMessage)
  const updatePlanMessageResponse = useChatStore((s) => s.updatePlanMessageResponse)
  const updateConversationTitle = useChatStore((s) => s.updateConversationTitle)

  // Sync authenticated user ID to store when auth state changes
  useEffect(() => {
    const userId = user?.id ?? null
    setCurrentUser(userId)
  }, [user?.id, setCurrentUser])

  /**
   * Classify a transport failure as auth-related or generic connection error.
   * Used when the backend is healthy but the WebSocket/SSE connection failed,
   * which typically means the auth cookie or token drifted.
   */
  const getTransportFailure = useCallback(
    (message: string, details?: string): { code: ErrorCode; message: string; details?: string } => {
      if (!authRequired) {
        return { code: 'connection.failed', message, details }
      }
      if (authError === 'RefreshAccessTokenError' || isLikelyAuthRelatedTransportError(message)) {
        return {
          code: 'auth.session_expired' as ErrorCode,
          message: 'Your session has expired. Please sign in again to continue.',
          details,
        }
      }
      return { code: 'connection.failed', message, details }
    },
    [authRequired, authError]
  )

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
        // A response on the wire proves the post-rotation auth is alive --
        // clear the consecutive auth_expired counter so a *future* (and
        // therefore independent) auth_expired starts the silent-reconnect
        // budget from zero again.
        consecutiveAuthExpiredRef.current = 0

        if (isStaleMessage(parentId)) {
          console.warn('Dropping stale system_response (parent_id mismatch)', { parentId, active: wsClientRef.current?.activeParentId })
          return
        }

        // If the UI is no longer streaming, this response belongs to a
        // workflow that outlived its request lifecycle. Drop it before adding
        // content; otherwise stale final responses can duplicate agent replies.
        const { isStreaming: currentlyStreaming } = useChatStore.getState()
        if (!currentlyStreaming) {
          console.warn(
            isFinal
              ? 'Ignoring stale isFinal -- not currently streaming'
              : 'Ignoring stale system_response -- not currently streaming'
          )
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

          // Derive a conversation title from the plan (preferred) or fall
          // back to the last user message.
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
              // Skip simple greetings.
              if (lastUserMsg && lastUserMsg.content.length > 10) {
                extractedTitle = lastUserMsg.content
              }
            }

            if (extractedTitle) {
              // Clean up the title
              const cleanTitle = extractedTitle
                .replace(/^\*+|\*+$/g, '')
                .replace(/^["']|["']$/g, '')
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

          // Empty-content tracking message carries job metadata for session
          // restoration; AgentResponse returns null for empty content so it
          // won't render.
          const messageId = addAgentResponseWithMeta(
            '',
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
          // Keep isStreaming=true to block input -- deep research SSE will
          // release it on completion.
          setLoading(false)
          // Don't add this as final response - let SSE handle the rest
          return
        }

        // reportContent is only populated by deep research SSE events
        // (use-deep-research.ts), not by regular WebSocket responses.
        if (content && content.trim()) {
          // Add to chat area as AgentResponse
          // Note: reportContent is only set by deep research SSE events (use-deep-research.ts)
          addAgentResponse(content)
        }

        // status: "complete" with null text signals task completion
        if (isFinal) {
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

          // Workflow finished cleanly -- drop the resend buffer.
          lastSentOutgoingRef.current = null
        }
      },

      onIntermediateStep: (content: NATIntermediateStepContent | string, status: string, _parentId?: string) => {
        // Same as onResponse: any backend-emitted frame on this socket
        // proves the rotated handshake is honoured. Reset the consecutive
        // auth_expired budget.
        consecutiveAuthExpiredRef.current = 0

        // NAT uses an internal step ID (not the user message ID) for
        // parent_id on intermediate steps, so we can't stale-detect via
        // parent_id. Guard on isStreaming instead: if not streaming, the
        // workflow was already cancelled/disconnected.
        const { isStreaming: currentlyStreaming } = useChatStore.getState()
        if (!currentlyStreaming) {
          console.warn('Ignoring stale intermediate step -- not currently streaming')
          return
        }
        // Legacy string-content path: synthesize a generic thinking step.
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
          // Defensive: shouldn't usually fire (a step is normally either new
          // or transitioning to complete), but handle gracefully.
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

        // Add to local plan state FIRST so it's captured when the prompt message is
        // saved (addAgentPrompt below snapshots planMessages for session
        // restoration).
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
        // Auth expired mid-workflow: backend contract is `code ===
        // 'user_auth_error'` + `message === 'auth_expired'` (see
        // websocket_reconnect.py `_send_auth_expired_error`). Buffer the
        // just-sent payload, rotate the socket, and let
        // `onConnectionChange('connected')` re-issue the message once the
        // fresh handshake completes. We deliberately do NOT touch
        // `isStreaming` or the thinking step so the user's "request in
        // progress" UX bridges the rotation seamlessly.
        //
        // Match BOTH fields, not just `message`. A future application
        // error that happens to carry `message: 'auth_expired'` (agent
        // text, validation message) would otherwise be silently swallowed
        // and trigger a phantom reconnect instead of surfacing as a
        // banner.
        if (errorContent.code === 'user_auth_error' && errorContent.message === 'auth_expired') {
          // Cap on consecutive auth_expired rotations: without it, a
          // stale-NextAuth-cache or clock-skew condition can drive a
          // silent rotation loop -- rotate() resets reconnectCount, so
          // the WS client's own CONNECTION_FAILED safety net never
          // triggers on this path. See MAX_CONSECUTIVE_AUTH_EXPIRED.
          consecutiveAuthExpiredRef.current += 1
          if (consecutiveAuthExpiredRef.current > MAX_CONSECUTIVE_AUTH_EXPIRED) {
            consecutiveAuthExpiredRef.current = 0
            lastSentOutgoingRef.current = null
            pendingOutgoingRef.current = null
            addErrorCard(
              'auth.session_expired' as ErrorCode,
              'Your session has expired. Please sign in again to continue.',
              errorContent.details,
            )
            setCurrentStatus(null)
            setStreaming(false)
            setLoading(false)
            clearPendingInteraction()
            return
          }

          const lastSent = lastSentOutgoingRef.current
          if (lastSent) {
            pendingOutgoingRef.current = lastSent
          }
          rotateSocket('auth_expired')
          return
        }

        // Connection failure (all client retries exhausted) -- gate the UI
        // on a health check so we can distinguish "backend down" from a
        // likely auth/cookie drift.
        if (errorContent.code === 'CONNECTION_FAILED') {
          const backendUp = await checkBackendHealthCached()

          const errorInfo = backendUp
            ? getTransportFailure(errorContent.message, errorContent.details)
            : { code: 'connection.failed' as const, message: errorContent.message, details: errorContent.details }

          addErrorCard(errorInfo.code, errorInfo.message, errorInfo.details)
          setCurrentStatus(null)
          setStreaming(false)
          setLoading(false)
          clearPendingInteraction()
          // UI is now in a failure state. Drop both buffers so a later
          // recovery-driven `connected` cannot silently replay the
          // pre-rotation payload behind the user's back.
          lastSentOutgoingRef.current = null
          pendingOutgoingRef.current = null
          return
        }

        // Application-level errors from the backend (agent errors, etc.).
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
        // Symmetric with CONNECTION_FAILED: any buffered outgoing payload
        // (preflight rotation, auth_expired) is no longer something the
        // user expects to be re-sent once we've shown them an error card.
        lastSentOutgoingRef.current = null
        pendingOutgoingRef.current = null
      },

      onConnectionChange: (status, context?: ConnectionChangeContext) => {
        setIsConnected(status === 'connected')

        if (status === 'connected') {
          invalidateHealthCache()
          dismissConnectionErrors()

          // Drain any payload buffered by a pre-flight rotation or
          // `auth_expired`. Keeps the UX silent: the user acted once and
          // it goes out the moment the fresh socket is up. Dispatch by
          // `kind` so both chat messages AND HITL interaction responses
          // survive a rotation -- the backend's per-message expiry gate
          // applies to both.
          const pending = pendingOutgoingRef.current
          const client = wsClientRef.current
          if (pending && client) {
            pendingOutgoingRef.current = null
            if (pending.kind === 'message') {
              client.sendMessage(pending.content, pending.dataSources)
            } else {
              client.sendInteractionResponse(
                pending.interactionId,
                pending.parentId,
                pending.response,
              )
            }
            // Mirror doSend(): the drain just put a payload on the wire,
            // so it is now the canonical "last sent". Without this, a
            // pre-flight rotation that gets immediately hit by a second
            // `auth_expired` on the fresh socket would have a null
            // `lastSentOutgoingRef` and silently drop the user's payload
            // (the auth_expired handler couldn't re-buffer it).
            lastSentOutgoingRef.current = pending
            // Match each send path's loading contract: chat sends clear the
            // composer spinner after putting the message on the wire, while
            // HITL answers keep it visible until the backend processes them.
            setLoading(pending.kind === 'interaction')
          }
          return
        }

        // Intentional disconnects (session switch, cleanup) shouldn't
        // surface as errors.
        if (context?.intentional) return

        if (status === 'error' || status === 'disconnected') {
          // Don't show error cards here -- the WS client only fires
          // onError(CONNECTION_FAILED) after all retries are exhausted,
          // and the health-check gate there decides whether to show UI.
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
    getTransportFailure,
    rotateSocket,
  ])

  /**
   * Initialize WebSocket client when conversation changes
   */
  const currentConversationId = currentConversation?.id

  useEffect(() => {
    if (!currentConversationId || !autoConnect) return

    // Create new client if needed
    if (!wsClientRef.current) {
      wsClientRef.current = createNATWebSocketClient({
        conversationId: currentConversationId,
        callbacks: createCallbacks(),
        onBeforeReconnect: refreshAuthBeforeReconnect,
      })
      wsClientRef.current.connect()
    } else {
      // Update conversation ID on existing client
      wsClientRef.current.updateConversationId(currentConversationId)
    }

    // Cleanup on unmount or conversation switch.
    //
    // CRITICAL: the resend buffers (pendingOutgoingRef,
    // lastSentOutgoingRef) and the consecutive-auth_expired counter are
    // conversation-scoped state. If we leave them populated across a
    // conversation switch, the next conversation's freshly-handshaken
    // socket would drain a payload from the previous conversation into
    // its own backend session on the first `connected` event -- a
    // user-data leak across conversation boundaries.
    //
    // Same goes for currentThinkingStepIdRef / currentStatusRef:
    // stale IDs from the previous conversation must not be reused
    // against the new socket.
    return () => {
      if (wsClientRef.current) {
        wsClientRef.current.disconnect()
        wsClientRef.current = null
      }
      const { isStreaming: wasStreaming, isLoading: wasLoading, currentStatus: status } =
        useChatStore.getState()
      if (wasStreaming || wasLoading || status !== null) {
        setStreaming(false)
        setLoading(false)
        setCurrentStatus(null)
      }
      pendingOutgoingRef.current = null
      lastSentOutgoingRef.current = null
      consecutiveAuthExpiredRef.current = 0
      pendingRotationRef.current = false
      currentThinkingStepIdRef.current = null
      currentStatusRef.current = null
    }
  }, [
    currentConversationId,
    autoConnect,
    createCallbacks,
    refreshAuthBeforeReconnect,
    setStreaming,
    setLoading,
    setCurrentStatus,
  ])

  /**
   * Send a message via WebSocket
   */
  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim()) return

      // Collect metadata about data sources and files before adding user message
      const layoutState = useLayoutStore.getState()
      const enabledDataSources = layoutState.enabledDataSourceIds

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

      // currentConversation may have just been created inside addUserMessage.
      const storeState = useChatStore.getState()
      const conversationId = storeState.currentConversation?.id

      // thinkingSteps are NOT cleared here -- they persist per userMessageId
      // so chat history still renders prior thinking blocks.
      clearReportContent()
      clearPendingInteraction()

      // Reset tracking refs
      currentThinkingStepIdRef.current = null
      currentStatusRef.current = null

      // Set initial status; first real step will be "Workflow: Chat Researcher" from backend
      setCurrentStatus('thinking')
      setStreaming(true)
      setLoading(true)

      const outgoingPayload: PendingOutgoing = {
        kind: 'message',
        content,
        dataSources: dataSourcesForMessage,
      }

      // Helper to actually send the message
      const doSend = () => {
        if (wsClientRef.current?.isConnected()) {
          wsClientRef.current.sendMessage(content, dataSourcesForMessage)
          // Remember the payload so a mid-workflow `auth_expired` can
          // transparently re-issue it after the reconnect. Cleared on
          // isFinal or any non-auth error.
          lastSentOutgoingRef.current = outgoingPayload
          setLoading(false)
        } else {
          addErrorCard('connection.failed', 'WebSocket connection failed')
          setStreaming(false)
          setLoading(false)
        }
      }

      // Pre-flight: the socket may report connected, but if its JWT is
      // already past `exp` (e.g. after a long idle / laptop sleep) the
      // backend is still trusting a dead token. Buffer + rotate; the
      // buffer is drained from `onConnectionChange('connected')`.
      const tokenIsStale = (): boolean => {
        if (!authRequired || !activeSocketTokenExpiresAt) return false
        return Date.now() >= activeSocketTokenExpiresAt * 1000
      }

      if (wsClientRef.current?.isConnected() && tokenIsStale()) {
        pendingOutgoingRef.current = outgoingPayload
        rotateSocket('preflight')
        return
      }

      if (wsClientRef.current?.isConnected()) {
        doSend()
      } else if (conversationId) {
        // A client can exist but still be handshaking or reconnecting.
        // Queue this outbound payload for the normal 'connected' drain
        // instead of replacing the client and creating a parallel socket.
        pendingOutgoingRef.current = outgoingPayload

        if (!wsClientRef.current) {
          wsClientRef.current = createNATWebSocketClient({
            conversationId,
            callbacks: createCallbacks(),
            onBeforeReconnect: refreshAuthBeforeReconnect,
          })
        }
        void wsClientRef.current.connect()
      } else {
        // Defensive: shouldn't happen because addUserMessage creates a
        // conversation if one is missing.
        addErrorCard('system.unknown', 'No active conversation')
        setStreaming(false)
        setLoading(false)
      }
    },
    [
      addUserMessage,
      addErrorCard,
      clearReportContent,
      clearPendingInteraction,
      setCurrentStatus,
      setStreaming,
      setLoading,
      createCallbacks,
      refreshAuthBeforeReconnect,
      rotateSocket,
      authRequired,
      activeSocketTokenExpiresAt,
    ]
  )

  /**
   * Respond to a pending interaction (clarification, approval, etc.)
   *
   * Mirrors `sendMessage`'s rotation handling: the backend applies the
   * same per-message JWT expiry gate to `WebSocketUserInteractionResponseMessage`
   * as it does to chat messages, so a HITL response that lands right after
   * token expiry would otherwise be silently lost (no `lastSentOutgoingRef`
   * for the rotation handler to replay). Preflight on stale token, buffer
   * the typed payload, and let `onConnectionChange('connected')` drain it
   * via `sendInteractionResponse` once the fresh handshake completes.
   */
  const respondToInteraction = useCallback(
    (response: string) => {
      if (!pendingInteraction) {
        console.warn('No pending interaction to respond to')
        return
      }

      // Mark the most recent unanswered prompt message as responded.
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

      const interactionPayload: PendingOutgoing = {
        kind: 'interaction',
        interactionId: pendingInteraction.id,
        parentId: pendingInteraction.parentId,
        response,
      }

      const doSend = () => {
        if (wsClientRef.current?.isConnected()) {
          wsClientRef.current.sendInteractionResponse(
            pendingInteraction.id,
            pendingInteraction.parentId,
            response
          )
          // Record the HITL payload so a follow-up `auth_expired` can
          // transparently re-issue THIS response (not a stale chat
          // payload that happened to be the previous `lastSentOutgoing`).
          lastSentOutgoingRef.current = interactionPayload
          setStreaming(true)
          setLoading(true)
        } else {
          addErrorCard('connection.failed', 'WebSocket not connected')
        }
      }

      // Stale-token pre-flight (mirrors sendMessage): the socket may
      // report connected, but if the handshake JWT is already past `exp`
      // the backend will respond with `auth_expired` and our HITL response
      // would be lost. Buffer + rotate; the drain re-issues it.
      const tokenIsStale = (): boolean => {
        if (!authRequired || !activeSocketTokenExpiresAt) return false
        return Date.now() >= activeSocketTokenExpiresAt * 1000
      }

      if (wsClientRef.current?.isConnected() && tokenIsStale()) {
        pendingOutgoingRef.current = interactionPayload
        // Keep the "working" UX visible across the rotation so the user
        // doesn't see their answer disappear into an idle screen.
        setStreaming(true)
        setLoading(true)
        rotateSocket('preflight-interaction')
        return
      }

      doSend()
    },
    [
      pendingInteraction,
      currentConversation?.messages,
      respondToPrompt,
      updatePlanMessageResponse,
      addErrorCard,
      setStreaming,
      setLoading,
      authRequired,
      activeSocketTokenExpiresAt,
      rotateSocket,
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
        onBeforeReconnect: refreshAuthBeforeReconnect,
      })
      wsClientRef.current.connect()
    }
  }, [currentConversation, createCallbacks, refreshAuthBeforeReconnect])

  // Activate recovery polling when connection error cards are visible
  useConnectionRecovery(connect)

  /**
   * Soft-rotation timer. If idle when it fires, rotate immediately; if a
   * stream is in flight, set `pendingRotationRef` and let the deferred
   * effect below rotate once the stream ends so we never cut a response.
   */
  useEffect(() => {
    if (!authRequired || !activeSocketTokenExpiresAt) return

    let cancelled = false
    let softTimer: ReturnType<typeof setTimeout> | undefined

    const onSoftFire = (): void => {
      if (cancelled) return
      if (useChatStore.getState().isStreaming) {
        pendingRotationRef.current = true
        return
      }
      rotateSocket('soft')
    }

    const now = Date.now()
    const expMs = activeSocketTokenExpiresAt * 1000
    const softAt = expMs - WS_REFRESH_SOFT_GUARD_SECONDS * 1000

    if (softAt > now) {
      softTimer = setTimeout(onSoftFire, softAt - now)
    } else {
      // Already inside the soft window on first effect run (e.g. mount
      // with a near-expiry token).
      onSoftFire()
    }

    return () => {
      cancelled = true
      if (softTimer) clearTimeout(softTimer)
    }
  }, [activeSocketTokenExpiresAt, authRequired, rotateSocket])

  /**
   * Drains a deferred rotation the moment the stream ends. Cleared
   * synchronously so a follow-up stream doesn't double-rotate before the
   * next soft timer arms.
   */
  useEffect(() => {
    if (!isStreaming && pendingRotationRef.current) {
      pendingRotationRef.current = false
      rotateSocket('deferred')
    }
  }, [isStreaming, rotateSocket])

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

  const messages = currentConversation?.messages ?? EMPTY_MESSAGES
  const userConversations = useMemo(
    () => (currentUserId ? conversations.filter((c) => c.userId === currentUserId) : EMPTY_CONVERSATIONS),
    [conversations, currentUserId]
  )

  return {
    sendMessage,
    respondToInteraction,
    disconnect,
    connect,
    isConnected,
    isStreaming,
    isLoading,
    messages,
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
