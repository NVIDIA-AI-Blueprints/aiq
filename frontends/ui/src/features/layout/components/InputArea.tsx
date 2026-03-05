// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * InputArea Component
 *
 * Chat input area at the bottom of the chat view.
 * Includes text input, tool buttons, and send action.
 * Supports both SSE (useChat) and WebSocket (useWebSocketChat) connections.
 *
 * When there's a pending interaction (HITL prompt), the input switches
 * to response mode and uses respondToInteraction instead of sendMessage.
 *
 * Disabled state when user is not authenticated.
 */

'use client'

import { type FC, useState, useCallback, useRef, useEffect, type KeyboardEvent } from 'react'
import { Flex, Text, Button, TextArea, Banner, Popover } from '@/adapters/ui'
import { useChat, useWebSocketChat, useChatStore, useIsCurrentSessionBusy } from '@/features/chat'
import { useLayoutStore } from '../store'
import { useAppConfig } from '@/shared/context'
import { useFileUpload, useFileDragDrop, useFileUploadBanners } from '@/features/documents'
import { Wand, Globe, Document, Paperclip, Paperplane, Cancel } from '@/adapters/ui/icons'

/** Connection mode for the chat */
export type ConnectionMode = 'sse' | 'websocket'

interface InputAreaProps {
  /** Placeholder text */
  placeholder?: string
  /** Whether the user is authenticated */
  isAuthenticated?: boolean
  /** Connection mode: 'sse' for SSE endpoint, 'websocket' for WebSocket (default: 'sse') */
  connectionMode?: ConnectionMode
}

/**
 * Chat input component with text area and action buttons.
 * Positioned at the bottom of the chat area.
 *
 * Supports two connection modes:
 * - 'sse': Uses SSE endpoint (/generate/stream) via useChat hook
 * - 'websocket': Uses WebSocket for full HITL support via useWebSocketChat hook
 *
 * When pendingInteraction exists, input switches to response mode:
 * - Different placeholder text
 * - Uses respondToInteraction instead of sendMessage
 * - Shows visual indicator
 */
export const InputArea: FC<InputAreaProps> = ({
  placeholder = 'Check data sources and ask a research question...',
  isAuthenticated = false,
  connectionMode = 'sse',
}) => {
  const [message, setMessage] = useState('')

  // File input ref for attachment button
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Get file upload configuration from app config
  const { fileUpload: fileUploadConfig } = useAppConfig()

  // Check if current session is busy with operations
  const isBusy = useIsCurrentSessionBusy()

  // Use appropriate hook based on connection mode
  const sseChat = useChat()
  const wsChat = useWebSocketChat({ autoConnect: connectionMode === 'websocket' })

  // Get current conversation for filtering files and ensureSession for auto-creation
  const currentConversation = useChatStore((state) => state.currentConversation)
  const ensureSession = useChatStore((state) => state.ensureSession)

  // Deep research completion state - disables new submissions after research completes
  const deepResearchStatus = useChatStore((state) => state.deepResearchStatus)
  const isDeepResearchStreaming = useChatStore((state) => state.isDeepResearchStreaming)
  const deepResearchOwnerConversationId = useChatStore((state) => state.deepResearchOwnerConversationId)

  // Check for active deep research in conversation messages (persisted state)
  // This handles the case where ephemeral state has been reset (page refresh, session switch)
  const hasActiveDeepResearch = useChatStore((state) => {
    if (!state.currentConversation?.messages) return false
    return state.currentConversation.messages.some(
      (m) =>
        m.messageType === 'agent_response' &&
        m.deepResearchJobId &&
        (m.deepResearchJobStatus === 'submitted' || m.deepResearchJobStatus === 'running')
    )
  })

  // Check for completed deep research in conversation messages (persisted state)
  // This handles the case where ephemeral state has been reset (page refresh, session switch)
  const hasCompletedDeepResearch = useChatStore((state) => {
    if (!state.currentConversation?.messages) return false
    return state.currentConversation.messages.some(
      (m) =>
        m.messageType === 'agent_response' &&
        m.deepResearchJobId &&
        (m.deepResearchJobStatus === 'success' ||
          m.deepResearchJobStatus === 'failure' ||
          m.deepResearchJobStatus === 'interrupted')
    )
  })

  // Research session is complete when:
  // 1. Ephemeral state shows terminal status AND stream has finished, OR
  // 2. Persisted message has terminal deep research job status
  const isResearchSessionComplete =
    (!isDeepResearchStreaming &&
      (deepResearchStatus === 'success' ||
        deepResearchStatus === 'failure' ||
        deepResearchStatus === 'interrupted')) ||
    hasCompletedDeepResearch

  // Research session is in progress when:
  // 1. Ephemeral state is streaming, OR
  // 2. Persisted message has an active deep research job status
  const isResearchSessionInProgress =
    (isDeepResearchStreaming && deepResearchOwnerConversationId === currentConversation?.id) ||
    hasActiveDeepResearch

  // File upload hook - provides session files and handles validation internally
  const {
    uploadFiles,
    sessionFiles,
    isUploading,
    error: uploadError,
    clearError,
  } = useFileUpload({
    sessionId: currentConversation?.id,
  })

  // File upload banner hook - monitors file status and triggers banner messages in chat
  useFileUploadBanners()

  // -- Pending files warning state --
  // Tracks whether we've shown the pending-files warning for the current upload batch.
  // When true, the next submit will dismiss the warning and send the message.
  const [pendingFilesWarningActive, setPendingFilesWarningActive] = useState(false)

  // Track the number of uploading/ingesting files so we can detect NEW upload interactions
  // and reset the acknowledged state.
  const prevPendingCountRef = useRef(0)

  // Store actions for the warning banner
  const addFileUploadStatusCard = useChatStore((state) => state.addFileUploadStatusCard)
  const removeFileUploadWarning = useChatStore((state) => state.removeFileUploadWarning)

  // Compute pending files count for the current session
  const pendingSessionFiles = sessionFiles.filter(
    (f) => f.status === 'uploading' || f.status === 'ingesting'
  )
  const pendingCount = pendingSessionFiles.length

  // Detect NEW file upload interactions: when pendingCount increases from 0 (or from a lower value
  // after all files finished) to > 0, it means the user started a new upload batch.
  // Reset the warning state so it can trigger again on the next submit.
  //
  // Also: if the warning is currently displayed and all files finish ingesting,
  // auto-dismiss the warning since the files are now ready.
  useEffect(() => {
    const prev = prevPendingCountRef.current
    // New upload detected: pending count went from 0 → >0
    if (prev === 0 && pendingCount > 0) {
      setPendingFilesWarningActive(false)
    }
    // Files all finished while warning was active → auto-dismiss the warning
    if (prev > 0 && pendingCount === 0 && pendingFilesWarningActive) {
      removeFileUploadWarning()
      setPendingFilesWarningActive(false)
    }
    prevPendingCountRef.current = pendingCount
  }, [pendingCount, pendingFilesWarningActive, removeFileUploadWarning])

  // Select the active hook's methods based on mode
  const activeChat = connectionMode === 'websocket' ? wsChat : sseChat
  const { sendMessage, isLoading, respondToInteraction, pendingInteraction } = activeChat

  // Register respondToInteraction in the store so sibling components (e.g. AgentPrompt) can use it
  const setRespondToInteractionFn = useChatStore((state) => state.setRespondToInteractionFn)
  useEffect(() => {
    setRespondToInteractionFn(respondToInteraction)
    return () => setRespondToInteractionFn(null)
  }, [respondToInteraction, setRespondToInteractionFn])

  // Layout store for opening data sources panel
  const {
    rightPanel,
    openRightPanel,
    closeRightPanel,
    setDataSourcesPanelTab,
    enabledDataSourceIds,
    knowledgeLayerAvailable,
    availableDataSources,
  } = useLayoutStore()

  // Check if we're in response mode (responding to a HITL prompt)
  const isResponseMode = !!pendingInteraction

  // DISABLE LOGIC
  // Disable input when:
  // 1. Not authenticated
  // 2. Session is busy AND not in HITL response mode (user must be able to type approve/reject)
  // 3. Deep research has completed/failed

  const isDisabledByAuth = !isAuthenticated
  const disabled = isDisabledByAuth || (isBusy && !isResponseMode) || isResearchSessionComplete

  // Dynamic placeholder based on state
  // Note: isResponseMode is checked before isBusy because the user needs to
  // see the response prompt even when the session is "busy" due to HITL.
  const getPlaceholder = (): string => {
    if (!isAuthenticated) return 'Sign in to start researching'
    if (isResearchSessionComplete)
      return 'Research completed. Create a new session for further questions.'
    if (isResponseMode) return 'Type your response to the agent...'
    if (isBusy) return 'Please wait...'
    return placeholder
  }

  const handleSubmit = useCallback(async () => {
    if (!message.trim() || disabled) return
    const currentMessage = message.trim()

    // HITL responses always go through immediately — no file-pending check
    if (isResponseMode && respondToInteraction) {
      setMessage('')
      respondToInteraction(currentMessage)
      return
    }

    // --- Pending files warning logic ---
    // If files are still uploading/ingesting AND we haven't shown the warning yet:
    // 1. Add a warning banner to the chat feed
    // 2. Keep the message in the input (don't clear or send)
    // 3. Mark warning as active so the next submit will proceed
    if (pendingCount > 0 && !pendingFilesWarningActive) {
      addFileUploadStatusCard('pending_warning', pendingCount, `pending-warning-${Date.now()}`)
      setPendingFilesWarningActive(true)
      return // Don't send — keep message in input
    }

    // If the warning is currently active (user is re-submitting to acknowledge):
    // Dismiss the warning banner first, then send the message
    if (pendingFilesWarningActive) {
      removeFileUploadWarning()
      setPendingFilesWarningActive(false)
    }

    // Proceed with normal send
    setMessage('')
    await sendMessage(currentMessage)
  }, [
    message,
    disabled,
    isResponseMode,
    respondToInteraction,
    sendMessage,
    pendingCount,
    pendingFilesWarningActive,
    addFileUploadStatusCard,
    removeFileUploadWarning,
  ])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit]
  )

  const handleValueChange = useCallback(
    (value: string) => {
      if (isDisabledByAuth) return // Don't allow typing when not authenticated
      setMessage(value)
    },
    [isDisabledByAuth]
  )

  // Handle attach button click
  const handleAttachClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFilesSelected = useCallback(
    async (files: File[]) => {
      if (files.length === 0 || isDisabledByAuth || isUploading || isBusy) return

      const sessionId = ensureSession()
      if (!sessionId) {
        console.error('Failed to create session for upload')
        return
      }

      // Open the files tab immediately so the user sees instant feedback
      setDataSourcesPanelTab('files')
      openRightPanel('data-sources')

      // uploadFiles validates internally and sets error if invalid
      await uploadFiles(files, sessionId)
    },
    [
      ensureSession,
      uploadFiles,
      openRightPanel,
      setDataSourcesPanelTab,
      isDisabledByAuth,
      isUploading,
      isBusy,
    ]
  )

  const { isDragging, isUnsupportedDrag, dragHandlers } = useFileDragDrop({
    onDrop: handleFilesSelected,
    disabled: isDisabledByAuth || isUploading || isBusy,
  })

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || [])
      await handleFilesSelected(files)
      // Reset input so same file can be selected again
      e.target.value = ''
    },
    [handleFilesSelected]
  )

  // Count of attached files (successful or in progress) for current session
  const attachedFilesCount = sessionFiles.filter(
    (f) => f.status === 'uploading' || f.status === 'ingesting' || f.status === 'success'
  ).length

  // Data sources counts for indicator
  const enabledSourcesCount = enabledDataSourceIds.length
  const totalSourcesCount = availableDataSources?.length ?? 0

  return (
    <Flex direction="col" className="mx-auto w-full max-w-3xl p-4">
      <Flex
        direction="col"
        className={`
          bg-surface-raised relative rounded-2xl border border-black p-4 transition-colors
          ${isDisabledByAuth ? 'opacity-60' : ''}
          ${isDragging && isUnsupportedDrag ? 'border-error border-dashed' : isDragging ? 'border-brand border-dashed' : ''}
        `}
        {...dragHandlers}
      >
        {/* Drag overlay */}
        {isDragging && (
          <div className="bg-surface-raised-90 absolute inset-0 z-10 flex items-center justify-center rounded-2xl">
            <Flex direction="col" align="center" gap="2">
              {isUnsupportedDrag ? (
                <Cancel className="text-error h-8 w-8" />
              ) : (
                <Paperclip className="text-brand h-8 w-8" />
              )}
              <Text
                kind="label/semibold/sm"
                className={isUnsupportedDrag ? 'text-error' : 'text-brand'}
              >
                {isUnsupportedDrag ? 'Unsupported file type' : 'Drop files to upload'}
              </Text>
              {isUnsupportedDrag && (
                <Text kind="body/regular/xs" className="text-subtle">
                  Accepts: {fileUploadConfig.acceptedTypes}
                </Text>
              )}
            </Flex>
          </div>
        )}
        {/* Text Input */}
        <div onKeyDown={handleKeyDown}>
          <TextArea
            className="bg-surface-raised border-0"
            value={message}
            onValueChange={handleValueChange}
            placeholder={getPlaceholder()}
            disabled={disabled}
            resizeable="auto"
            size="medium"
            aria-label={isResponseMode ? 'Response input' : 'Chat message input'}
          />
        </div>

        {/* Upload Error Display */}
        {uploadError && (
          <Banner kind="inline" status="error" onClose={clearError} className="mt-2">
            {uploadError}
          </Banner>
        )}

        {/* Bottom Actions Bar */}
        <Flex align="center" justify="between" className="mt-3">
          {/* Left Actions: Mode selector only */}
          <Flex align="center" gap="2">
            {/* Mode selector */}
            <Popover
              side="top"
              align="start"
              slotContent={
                <Text kind="body/regular/sm" className="p-2">
                  Automatically route to appropriate agent based on inferred intent
                </Text>
              }
            >
              <Button kind="tertiary" size="tiny" disabled={isDisabledByAuth} aria-label="Query type">
                <Flex align="center" gap="1">
                  <Wand />
                  <Text kind="label/bold/sm">Auto</Text>
                </Flex>
              </Button>
            </Popover>
          </Flex>

          {/* Right Actions: Counters, Attach, Research, Submit */}
          <Flex align="center" gap="2">
            {/* Sources indicator - clickable to toggle data connections tab */}
            <Button
              kind="tertiary"
              size="tiny"
              onClick={() => {
                if (rightPanel === 'data-sources') {
                  closeRightPanel()
                } else {
                  setDataSourcesPanelTab('connections')
                  openRightPanel('data-sources')
                }
              }}
              disabled={isDisabledByAuth}
              aria-label="Toggle data sources connections"
              title="Selected data connections"
            >
              <Flex align="center" gap="1">
                <Globe className="h-3 w-3" />
                <Text kind="label/bold/sm">
                  {enabledSourcesCount}/{totalSourcesCount}
                </Text>
              </Flex>
            </Button>

            {/* Files indicator - clickable to toggle files tab */}
            <Button
              kind="tertiary"
              size="tiny"
              onClick={() => {
                if (rightPanel === 'data-sources') {
                  closeRightPanel()
                } else {
                  setDataSourcesPanelTab('files')
                  openRightPanel('data-sources')
                }
              }}
              disabled={isDisabledByAuth || !knowledgeLayerAvailable}
              aria-label="Open uploaded files"
              title={knowledgeLayerAvailable ? "Available files" : "File upload not available"}
            >
              <Flex align="center" gap="1">
                <Document className="h-3 w-3" />
                <Text kind="label/bold/sm">
                  {attachedFilesCount}
                </Text>
              </Flex>
            </Button>

            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={fileUploadConfig.acceptedTypes}
              className="hidden"
              onChange={handleFileChange}
            />

            {/* Attach files */}
            <Button
              kind="tertiary"
              size="small"
              onClick={handleAttachClick}
              disabled={isDisabledByAuth || isUploading || isBusy || !knowledgeLayerAvailable}
              aria-label="Attach files"
              title={
                isBusy
                  ? 'File upload disabled during active operations'
                  : !knowledgeLayerAvailable
                    ? 'File upload not available'
                    : 'Select files to upload'
              }
            >
              <Paperclip className="h-4 w-4" />
            </Button>

            {/* Send button - wrapped in Popover when research session is complete/in-progress.
                Exception: isResponseMode always shows the normal send button so users can
                submit HITL responses (approve/reject) even during active research. */}
            {isResearchSessionComplete && !isResponseMode ? (
              <Popover
                side="top"
                align="end"
                slotContent={
                  <Text kind="body/regular/sm" className="max-w-xs p-3">
                    Research completed. For further questions or reports, please create a new session.
                  </Text>
                }
              >
                <Button
                  kind="primary"
                  size="small"
                  aria-label="Research completed - create new session"
                  title="Research completed"
                >
                  <Paperplane className="h-4 w-4" />
                </Button>
              </Popover>
            ) : isResearchSessionInProgress && !isResponseMode ? (
              <Popover
                side="top"
                align="end"
                slotContent={
                  <Text kind="body/regular/sm" className="max-w-xs p-3">
                    Research is currently in progress. Chat is paused to prevent generating multiple reports at
                    the same time.
                  </Text>
                }
              >
                <Button
                  kind="primary"
                  size="small"
                  aria-label="Research in progress - please wait"
                  title="Research in progress"
                >
                  <Paperplane className="h-4 w-4" />
                </Button>
              </Popover>
            ) : (
              <Button
                kind="primary"
                size="small"
                color={!message.trim() || disabled ? undefined : 'brand'}
                onClick={handleSubmit}
                disabled={!message.trim() || disabled}
                aria-label={isResponseMode ? 'Send response' : 'Send message'}
                title="Send query"
              >
                {isLoading ? <span className="animate-pulse">...</span> : <Paperplane className="h-4 w-4" />}
              </Button>
            )}
          </Flex>
        </Flex>
      </Flex>
    </Flex>
  )
}
