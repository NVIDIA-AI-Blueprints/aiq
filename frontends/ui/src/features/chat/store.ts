// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Chat Store
 *
 * Zustand store for managing chat state including messages,
 * conversations, and streaming status.
 */

import { create } from 'zustand'
import { devtools, persist, createJSONStorage, type StorageValue, type PersistStorage } from 'zustand/middleware'
import { v4 as uuidv4 } from 'uuid'
import type {
  ChatStore,
  ChatState,
  Conversation,
  ChatMessage,
  StatusType,
  PromptType,
  PendingInteraction,
  FileCardData,
  ErrorCode,
  ThinkingStep,
  FileUploadStatusType,
  DeepResearchJobStatus,
  CitationSource,
  PlanMessage,
  DeepResearchLLMStep,
  DeepResearchAgent,
  DeepResearchToolCall,
  DeepResearchFile,
  DeepResearchBannerType,
} from './types'
import { getErrorMeta } from './lib/error-registry'
import {
  saveDeepResearchToSession,
  loadDeepResearchFromSession as _loadDeepResearchFromSession,
  clearDeepResearchSession,
  clearAllDeepResearchSessions,
} from './lib/deep-research-session-storage'
import { isUnavailableDeepResearchJobError } from './lib/deep-research-errors'
import { hasActiveDeepResearchJob } from './lib/session-activity'
import {
  logStorageWrite,
  logQuotaExceededPruning,
  logCriticalSessionsClear,
  logStorageAvailability,
  logExternalStorageEvent,
  logStoreHydration,
} from './lib/storage-logger'
import { pruneMessageForStorage } from './lib/prune-message-for-storage'
import { ensureStorageCapacity, checkStorageHealth } from './lib/storage-manager'
import { useLayoutStore } from '@/features/layout/store'
import { WEB_SEARCH_SOURCE_ID } from '@/features/layout/data-sources'

const isQuotaExceededError = (error: unknown): boolean => {
  if (!(error instanceof Error)) return false
  if (error.name === 'QuotaExceededError') return true
  return /quota|exceeded|storage/i.test(error.message)
}

type PersistedChatState = {
  currentUserId: ChatState['currentUserId']
  conversations: ChatState['conversations']
  currentConversation: ChatState['currentConversation']
  pendingInteraction: ChatState['pendingInteraction']
}

type PersistedChatStorageValue = StorageValue<PersistedChatState>

const prunePersistedChatState = (value: PersistedChatStorageValue): PersistedChatStorageValue => {
  const state = value.state

  const conversations: Conversation[] = (state.conversations ?? []).map((conv) => ({
    ...conv,
    messages: (conv.messages ?? []).map(pruneMessageForStorage),
  }))

  // Store only the ID reference — the full object already lives in conversations[].
  // On read, getItem reconstructs currentConversation from conversations by ID.
  // This avoids serializing the active session's messages twice in JSON.
  const currentConversationId = state.currentConversation?.id ?? null

  return {
    ...value,
    state: {
      currentUserId: state.currentUserId ?? null,
      conversations,
      currentConversation: currentConversationId as unknown as Conversation | null,
      pendingInteraction: state.pendingInteraction ?? null,
    },
  }
}

const createResilientStorage = (): PersistStorage<PersistedChatState> | undefined => {
  const base = createJSONStorage<PersistedChatState>(() => localStorage)
  if (!base) {
    logStorageAvailability(false)
    return undefined
  }

  return {
    getItem: async (name: string): Promise<PersistedChatStorageValue | null> => {
      const raw = await base.getItem(name)
      if (!raw) return null

      // Reconstruct currentConversation from the ID stored by prunePersistedChatState.
      const storedId = raw.state.currentConversation as unknown as string | null
      if (storedId) {
        const conversations = raw.state.conversations ?? []
        raw.state.currentConversation = conversations.find((c) => c.id === storedId) ?? null
      }

      return raw
    },
    removeItem: base.removeItem,
    setItem: (name: string, value: PersistedChatStorageValue) => {
      const prunedValue = prunePersistedChatState(value)

      try {
        base.setItem(name, prunedValue)
        logStorageWrite(prunedValue.state.conversations ?? [], prunedValue.state.currentUserId ?? null)
      } catch (error) {
        if (!isQuotaExceededError(error)) {
          throw error
        }

        const beforeConversations = prunedValue.state.conversations ?? []
        const beforeCount = beforeConversations.length
        const beforeSizeKB = Math.round(
          (JSON.stringify(beforeConversations).length * 2) / 1024
        )

        logQuotaExceededPruning(beforeCount, beforeCount, beforeSizeKB, beforeSizeKB)

        // Last resort: clear all conversations
        try {
          const lostSessionIds = beforeConversations.map((c) => c.id)

          base.removeItem(name)
          base.setItem(name, {
            ...value,
            state: {
              currentUserId: value.state.currentUserId ?? null,
              conversations: [],
              currentConversation: null,
              pendingInteraction: null,
            },
          })

          logCriticalSessionsClear(
            value.state.currentUserId ?? null,
            lostSessionIds,
            error
          )
        } catch (finalError) {
          console.error('[SessionsStore] ❌ CATASTROPHIC: Failed to clear sessions', {
            error: finalError instanceof Error ? finalError.message : String(finalError),
          })
        }
      }
    },
  }
}

const initialState: ChatState = {
  currentUserId: null,
  currentConversation: null,
  conversations: [],
  isStreaming: false,
  isLoading: false,
  // State for thinking steps association
  currentUserMessageId: null,
  // State for Details Panel
  thinkingSteps: [],
  activeThinkingStepId: null,
  reportContent: '',
  reportContentCategory: null,
  currentStatus: null,
  // State for HITL (human-in-the-loop)
  pendingInteraction: null,
  respondToInteractionFn: null,
  // State for deep research SSE streaming
  deepResearchJobId: null,
  deepResearchLastEventId: null,
  isDeepResearchStreaming: false,
  deepResearchStatus: null,
  deepResearchOwnerConversationId: null,
  activeDeepResearchMessageId: null,
  deepResearchCitations: [],
  deepResearchTodos: [],
  // State for ThinkingTab sub-tabs (LLM steps, agents, tool calls, files)
  deepResearchLLMSteps: [],
  deepResearchAgents: [],
  deepResearchToolCalls: [],
  deepResearchFiles: [],
  deepResearchStreamLoaded: false,
  // State for PlanTab
  planMessages: [],
}

/**
 * Create a new conversation with default values
 * @param userId - The user ID who owns this conversation
 */
const createNewConversation = (userId: string): Conversation => ({
  id: `s_${uuidv4().replace(/-/g, '_')}`, // Milvus: letters, numbers, underscores only (no hyphens)
  userId,
  title: 'New Session',
  messages: [],
  createdAt: new Date(),
  updatedAt: new Date(),
})

/**
 * Generate a title from the first user message
 */
const generateTitle = (content: string): string => {
  const maxLength = 50
  const trimmed = content.trim()
  if (trimmed.length <= maxLength) {
    return trimmed
  }
  return trimmed.substring(0, maxLength) + '...'
}

/**
 * Helper to update conversation in list
 */
const updateConversationInList = (
  conversations: Conversation[],
  updatedConversation: Conversation
): Conversation[] => {
  return conversations.map((c) => (c.id === updatedConversation.id ? updatedConversation : c))
}

const getDefaultEnabledDataSourceIds = (): string[] => {
  const layoutStore = useLayoutStore.getState()
  return (
    layoutStore.availableDataSources
      ?.filter((source) => source.id === WEB_SEARCH_SOURCE_ID)
      .map((source) => source.id) ?? []
  )
}

const restoreConversationDataSources = (conversation: Conversation): void => {
  const layoutStore = useLayoutStore.getState()

  if (conversation.enabledDataSourceIds) {
    const availableIds = new Set(layoutStore.availableDataSources?.map((source) => source.id) ?? [])
    const validIds = conversation.enabledDataSourceIds.filter((id) => availableIds.has(id))
    layoutStore.setEnabledDataSources(validIds)
    return
  }

  const defaultIds = getDefaultEnabledDataSourceIds()
  layoutStore.setEnabledDataSources(defaultIds)
}

export const useChatStore = create<ChatStore>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,

        setCurrentUser: (userId: string | null) => {
          const { conversations, currentConversation } = get()

          // Clear current conversation if:
          // 1. User is logging out (userId is null), OR
          // 2. User changed to a different user whose conversations don't include current one
          const shouldClearCurrent =
            currentConversation && (userId === null || currentConversation.userId !== userId)

          // Find first conversation for new user to auto-select
          const userConversations = userId ? conversations.filter((c) => c.userId === userId) : []
          const newCurrentConversation = shouldClearCurrent
            ? userConversations[0] || null
            : currentConversation

          set(
            {
              currentUserId: userId,
              currentConversation: newCurrentConversation,
            },
            false,
            'setCurrentUser'
          )

          // Restore session state from auto-selected conversation, or clear if none
          if (newCurrentConversation) {
            get().restoreSessionState(newCurrentConversation)
            restoreConversationDataSources(newCurrentConversation)
          } else {
            // No conversation selected - clear all ephemeral state
            set(
              {
                thinkingSteps: [],
                activeThinkingStepId: null,
                reportContent: '',
                reportContentCategory: null,
                currentStatus: null,
                planMessages: [],
                deepResearchCitations: [],
                deepResearchTodos: [],
                deepResearchLLMSteps: [],
                deepResearchAgents: [],
                deepResearchToolCalls: [],
                deepResearchFiles: [],
                deepResearchStreamLoaded: false,
                // Clear deep research job state
                deepResearchJobId: null,
                deepResearchLastEventId: null,
                isDeepResearchStreaming: false,
                deepResearchStatus: null,
                deepResearchOwnerConversationId: null,
                activeDeepResearchMessageId: null,
                // Clear HITL pending interaction
                pendingInteraction: null,
              },
              false,
              'setCurrentUser:clearState'
            )
          }
        },

        getUserConversations: () => {
          const { conversations, currentUserId } = get()
          if (!currentUserId) return []
          return conversations.filter((c) => c.userId === currentUserId)
        },

        createConversation: () => {
          const { currentUserId } = get()
          if (!currentUserId) {
            throw new Error('Cannot create conversation without authenticated user')
          }
          const layoutState = useLayoutStore.getState()
          const defaultEnabledDataSourceIds = getDefaultEnabledDataSourceIds()
          layoutState.setEnabledDataSources(defaultEnabledDataSourceIds)
          const newConversation: Conversation = {
            ...createNewConversation(currentUserId),
            enabledDataSourceIds: defaultEnabledDataSourceIds,
          }
          set(
            (state) => ({
              conversations: [newConversation, ...state.conversations],
              currentConversation: newConversation,
              // Clear all ResearchPanel content for new conversation
              thinkingSteps: [],
              activeThinkingStepId: null,
              reportContent: '',
              reportContentCategory: null,
              currentStatus: null,
              planMessages: [],
              deepResearchCitations: [],
              deepResearchTodos: [],
              deepResearchLLMSteps: [],
              deepResearchAgents: [],
              deepResearchToolCalls: [],
              deepResearchFiles: [],
              deepResearchStreamLoaded: false,
              // Clear deep research job state for new conversation
              deepResearchJobId: null,
              deepResearchLastEventId: null,
              isDeepResearchStreaming: false,
              deepResearchStatus: null,
              deepResearchOwnerConversationId: null,
              activeDeepResearchMessageId: null,
              // Clear HITL pending interaction
              pendingInteraction: null,
            }),
            false,
            'createConversation'
          )
          return newConversation
        },

        ensureSession: () => {
          const { currentConversation, currentUserId } = get()

          if (currentConversation?.id) {
            return currentConversation.id
          }
          if (!currentUserId) {
            return undefined
          }

          ensureStorageCapacity(currentConversation?.id ?? null, currentUserId)

          const layoutState = useLayoutStore.getState()
          const defaultEnabledDataSourceIds = getDefaultEnabledDataSourceIds()
          layoutState.setEnabledDataSources(defaultEnabledDataSourceIds)
          const newConversation: Conversation = {
            ...createNewConversation(currentUserId),
            enabledDataSourceIds: defaultEnabledDataSourceIds,
          }
          set(
            (state) => ({
              conversations: [newConversation, ...state.conversations],
              currentConversation: newConversation,
              // Clear all ResearchPanel content for new session
              thinkingSteps: [],
              activeThinkingStepId: null,
              reportContent: '',
              reportContentCategory: null,
              currentStatus: null,
              planMessages: [],
              deepResearchCitations: [],
              deepResearchTodos: [],
              deepResearchLLMSteps: [],
              deepResearchAgents: [],
              deepResearchToolCalls: [],
              deepResearchFiles: [],
              deepResearchStreamLoaded: false,
              // Clear deep research job state for new session
              deepResearchJobId: null,
              deepResearchLastEventId: null,
              isDeepResearchStreaming: false,
              deepResearchStatus: null,
              deepResearchOwnerConversationId: null,
              activeDeepResearchMessageId: null,
              // Clear HITL pending interaction
              pendingInteraction: null,
            }),
            false,
            'ensureSession'
          )
          return newConversation.id
        },

        selectConversation: (conversationId: string) => {
          const {
            conversations,
            currentUserId,
            currentConversation,
            isDeepResearchStreaming,
            deepResearchOwnerConversationId,
            activeDeepResearchMessageId,
            deepResearchLastEventId,
          } = get()

          if (currentConversation?.id !== conversationId) {
            ensureStorageCapacity(conversationId, currentUserId)
          }

          const conversation = conversations.find((c) => c.id === conversationId)

          if (conversation && conversation.userId === currentUserId) {
            // Save lastEventId if actively streaming before clearing
            if (
              currentConversation &&
              currentConversation.id !== conversationId &&
              isDeepResearchStreaming &&
              deepResearchOwnerConversationId === currentConversation.id &&
              activeDeepResearchMessageId
            ) {
              get().patchConversationMessage(
                deepResearchOwnerConversationId,
                activeDeepResearchMessageId,
                { deepResearchLastEventId: deepResearchLastEventId || undefined }
              )
              // Persist full deep research state to sessionStorage before clearing
              // so switching back can restore todos, citations, agents, etc.
              get().persistDeepResearchToSession()
            }

            // Close research panel when switching conversations
            // This ensures fresh data loads when panel is reopened
            useLayoutStore.getState().closeRightPanel()

            // Always clear deep research ephemeral state when switching conversations
            // SSE will be disconnected by hook cleanup when deepResearchJobId becomes null
            set(
              {
                currentConversation: conversation,
                deepResearchJobId: null,
                deepResearchLastEventId: null,
                isDeepResearchStreaming: false,
                deepResearchStatus: null,
                deepResearchOwnerConversationId: null,
                activeDeepResearchMessageId: null,
                deepResearchCitations: [],
                deepResearchTodos: [],
                deepResearchLLMSteps: [],
                deepResearchAgents: [],
                deepResearchToolCalls: [],
                deepResearchFiles: [],
                deepResearchStreamLoaded: false,
                reportContent: '',
                reportContentCategory: null,
              },
              false,
              'selectConversation'
            )

            // Restore basic session state (thinkingSteps) from messages
            get().restoreSessionState(conversation)
            restoreConversationDataSources(conversation)
          }
        },

        addUserMessage: (content: string, metadata?: { enabledDataSources?: string[]; messageFiles?: Array<{ id: string; fileName: string }> }) => {
          const { currentConversation, conversations, currentUserId } = get()

          // Create conversation if none exists
          let conversation = currentConversation
          if (!conversation) {
            if (!currentUserId) {
              throw new Error('Cannot create conversation without authenticated user')
            }
            const layoutState = useLayoutStore.getState()
            conversation = {
              ...createNewConversation(currentUserId),
              enabledDataSourceIds: [...layoutState.enabledDataSourceIds],
            }
          }

          const newMessage: ChatMessage = {
            id: uuidv4(),
            role: 'user',
            content,
            timestamp: new Date(),
            messageType: 'user',
            enabledDataSources: metadata?.enabledDataSources,
            messageFiles: metadata?.messageFiles,
          }

          // Update title if this is the first message
          const shouldUpdateTitle = conversation.messages.length === 0

          const updatedConversation: Conversation = {
            ...conversation,
            title: shouldUpdateTitle ? generateTitle(content) : conversation.title,
            messages: [...conversation.messages, newMessage],
            updatedAt: new Date(),
          }

          // Update conversations list
          const existingIndex = conversations.findIndex((c) => c.id === updatedConversation.id)
          let updatedConversations: Conversation[]

          if (existingIndex >= 0) {
            updatedConversations = updateConversationInList(conversations, updatedConversation)
          } else {
            updatedConversations = [updatedConversation, ...conversations]
          }

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
              isLoading: true,
              // Set current user message ID for associating thinking steps
              currentUserMessageId: newMessage.id,
              // Clear active thinking step for new request (but keep historical steps)
              activeThinkingStepId: null,
              // NOTE: planMessages and reportContent are NOT cleared here
              // They persist until a NEW deep research job starts (see startDeepResearch)
            },
            false,
            'addUserMessage'
          )

          return newMessage
        },

        startAssistantMessage: () => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) {
            throw new Error('No active conversation')
          }

          const newMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            messageType: 'assistant',
            isStreaming: true,
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, newMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
              isStreaming: true,
              isLoading: false,
            },
            false,
            'startAssistantMessage'
          )

          return newMessage
        },

        appendToAssistantMessage: (content: string) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const messages = currentConversation.messages
          const lastMessage = messages[messages.length - 1]

          if (!lastMessage || lastMessage.role !== 'assistant' || !lastMessage.isStreaming) {
            return
          }

          const updatedMessage: ChatMessage = {
            ...lastMessage,
            content: lastMessage.content + content,
          }

          const updatedMessages = [...messages.slice(0, -1), updatedMessage]

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'appendToAssistantMessage'
          )
        },

        completeAssistantMessage: () => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const messages = currentConversation.messages
          const lastMessage = messages[messages.length - 1]

          if (!lastMessage || lastMessage.role !== 'assistant') {
            set({ isStreaming: false }, false, 'completeAssistantMessage')
            return
          }

          const updatedMessage: ChatMessage = {
            ...lastMessage,
            isStreaming: false,
          }

          const updatedMessages = [...messages.slice(0, -1), updatedMessage]

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
              isStreaming: false,
            },
            false,
            'completeAssistantMessage'
          )
        },

        setLoading: (isLoading: boolean) => {
          set({ isLoading }, false, 'setLoading')
        },

        setStreaming: (isStreaming: boolean) => {
          set({ isStreaming }, false, 'setStreaming')
        },

        deleteConversation: (conversationId: string) => {
          const { currentConversation, conversations, deepResearchJobId, isDeepResearchStreaming } = get()

          // Find the conversation being deleted
          const conversationToDelete = conversations.find((c) => c.id === conversationId)

          // Check if this conversation has an active deep research job
          // Either from current ephemeral state (if deleting current conversation)
          // or from persisted message data
          let jobIdToCancel: string | null = null

          if (currentConversation?.id === conversationId && isDeepResearchStreaming && deepResearchJobId) {
            // Deleting current conversation with active streaming
            jobIdToCancel = deepResearchJobId
          } else if (conversationToDelete) {
            // Check if conversation has a job ID in its messages
            const lastAgentResponse = [...conversationToDelete.messages]
              .reverse()
              .find((m) => m.messageType === 'agent_response' && m.deepResearchJobId)

            if (lastAgentResponse?.deepResearchJobId &&
                lastAgentResponse.deepResearchJobStatus !== 'success' &&
                lastAgentResponse.deepResearchJobStatus !== 'failure' &&
                lastAgentResponse.deepResearchJobStatus !== 'interrupted') {
              // Job might still be running
              jobIdToCancel = lastAgentResponse.deepResearchJobId
            }
          }

          // Cancel the job asynchronously (fire and forget)
          if (jobIdToCancel) {
            import('@/adapters/api/deep-research-client').then(({ cancelJob }) => {
              cancelJob(jobIdToCancel!).catch((err) => {
                console.warn('Failed to cancel deep research job on session delete:', err)
              })
            })
          }

          const updatedConversations = conversations.filter((c) => c.id !== conversationId)

          // If deleting the current conversation with active streaming, clear deep research state
          const isCurrentWithActiveResearch = currentConversation?.id === conversationId && isDeepResearchStreaming

          set(
            {
              conversations: updatedConversations,
              currentConversation:
                currentConversation?.id === conversationId ? null : currentConversation,
              // Clear deep research state if deleting current conversation with active job
              ...(isCurrentWithActiveResearch && {
                deepResearchJobId: null,
                deepResearchLastEventId: null,
                isDeepResearchStreaming: false,
                deepResearchStatus: null,
                deepResearchOwnerConversationId: null,
                activeDeepResearchMessageId: null,
                deepResearchCitations: [],
                deepResearchTodos: [],
                deepResearchLLMSteps: [],
                deepResearchAgents: [],
                deepResearchToolCalls: [],
                deepResearchFiles: [],
                deepResearchStreamLoaded: false,
                reportContent: '',
                reportContentCategory: null,
              }),
            },
            false,
            'deleteConversation'
          )
        },

        deleteAllConversations: () => {
          const { conversations, currentUserId, currentConversation, isDeepResearchStreaming, deepResearchJobId } = get()

          if (!currentUserId) return

          // Get all conversations for the current user
          const userConversations = conversations.filter((c) => c.userId === currentUserId)

          // Collect job IDs from conversations with potentially active deep research
          const jobIdsToCancel: string[] = []

          // Add current streaming job if active
          if (isDeepResearchStreaming && deepResearchJobId) {
            jobIdsToCancel.push(deepResearchJobId)
          }

          // Check all user conversations for potentially active jobs
          for (const conv of userConversations) {
            const lastAgentResponse = [...conv.messages]
              .reverse()
              .find((m) => m.messageType === 'agent_response' && m.deepResearchJobId)

            if (lastAgentResponse?.deepResearchJobId &&
                lastAgentResponse.deepResearchJobStatus !== 'success' &&
                lastAgentResponse.deepResearchJobStatus !== 'failure' &&
                lastAgentResponse.deepResearchJobStatus !== 'interrupted' &&
                !jobIdsToCancel.includes(lastAgentResponse.deepResearchJobId)) {
              jobIdsToCancel.push(lastAgentResponse.deepResearchJobId)
            }
          }

          // Cancel all jobs asynchronously (fire and forget)
          if (jobIdsToCancel.length > 0) {
            import('@/adapters/api/deep-research-client').then(async ({ cancelJob }) => {
              const results = await Promise.allSettled(jobIdsToCancel.map((jobId) => cancelJob(jobId)))

              results.forEach((result, index) => {
                if (result.status === 'fulfilled') return
                console.warn(
                  'Failed to cancel deep research job on delete all sessions:',
                  jobIdsToCancel[index],
                  result.reason
                )
              })
            })
          }

          // Clear all deep research session storage
          clearAllDeepResearchSessions()

          // Filter out all conversations belonging to current user
          const remainingConversations = conversations.filter((c) => c.userId !== currentUserId)

          // Check if current conversation belongs to user being cleared
          const shouldClearCurrent = currentConversation && currentConversation.userId === currentUserId

          set(
            {
              conversations: remainingConversations,
              currentConversation: shouldClearCurrent ? null : currentConversation,
              // Clear all deep research state
              deepResearchJobId: null,
              deepResearchLastEventId: null,
              isDeepResearchStreaming: false,
              deepResearchStatus: null,
              deepResearchOwnerConversationId: null,
              activeDeepResearchMessageId: null,
              deepResearchCitations: [],
              deepResearchTodos: [],
              deepResearchLLMSteps: [],
              deepResearchAgents: [],
              deepResearchToolCalls: [],
              deepResearchFiles: [],
              deepResearchStreamLoaded: false,
              // Clear other ephemeral state
              thinkingSteps: [],
              activeThinkingStepId: null,
              reportContent: '',
              reportContentCategory: null,
              currentStatus: null,
              planMessages: [],
              pendingInteraction: null,
            },
            false,
            'deleteAllConversations'
          )
        },

        updateConversationTitle: (conversationId: string, title: string) => {
          const { currentConversation, conversations } = get()

          const updatedConversations = conversations.map((c) =>
            c.id === conversationId ? { ...c, title, updatedAt: new Date() } : c
          )

          const updatedCurrentConversation =
            currentConversation?.id === conversationId
              ? { ...currentConversation, title, updatedAt: new Date() }
              : currentConversation

          set(
            {
              conversations: updatedConversations,
              currentConversation: updatedCurrentConversation,
            },
            false,
            'updateConversationTitle'
          )
        },

        saveDataSourcesToConversation: (ids: string[]) => {
          let { currentConversation, conversations } = get()

          if (!currentConversation) {
            const sessionId = get().ensureSession()
            if (!sessionId) return
            currentConversation = get().currentConversation
            conversations = get().conversations
            if (!currentConversation) return
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            enabledDataSourceIds: ids,
          }

          set(
            {
              currentConversation: updatedConversation,
              conversations: updateConversationInList(conversations, updatedConversation),
            },
            false,
            'saveDataSourcesToConversation'
          )
        },

        // ============================================================
        // New actions for thinking/report content and status/prompts
        // ============================================================

        addThinkingStep: (step: Omit<ThinkingStep, 'id' | 'timestamp' | 'userMessageId'>) => {
          const { currentUserMessageId, currentConversation, conversations } = get()
          if (!currentUserMessageId) {
            console.warn('addThinkingStep called without currentUserMessageId')
            return ''
          }

          const stepId = uuidv4()
          const newStep: ThinkingStep = {
            ...step,
            id: stepId,
            userMessageId: currentUserMessageId,
            timestamp: new Date(),
          }

          // Update ephemeral store
          let updatedConversation = currentConversation
          let updatedConversations = conversations

          // Also persist to the user message in conversation for session persistence
          if (currentConversation) {
            const updatedMessages = currentConversation.messages.map((msg) => {
              if (msg.id === currentUserMessageId) {
                return {
                  ...msg,
                  thinkingSteps: [...(msg.thinkingSteps || []), newStep],
                }
              }
              return msg
            })

            updatedConversation = {
              ...currentConversation,
              messages: updatedMessages,
              updatedAt: new Date(),
            }

            updatedConversations = updateConversationInList(conversations, updatedConversation)
          }

          set(
            {
              thinkingSteps: [...get().thinkingSteps, newStep],
              activeThinkingStepId: stepId,
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'addThinkingStep'
          )

          return stepId
        },

        getThinkingStepsForMessage: (userMessageId: string) => {
          const { thinkingSteps } = get()
          // Filter out deep research steps - they're displayed in the Research Panel, not ChatThinking
          return thinkingSteps.filter((step) => step.userMessageId === userMessageId && !step.isDeepResearch)
        },

        appendToThinkingStep: (stepId: string, content: string) => {
          const { currentConversation, conversations, thinkingSteps } = get()

          // Update ephemeral store
          const updatedThinkingSteps = thinkingSteps.map((step) =>
            step.id === stepId ? { ...step, content: step.content + content } : step
          )

          // Find the userMessageId for this step to update persisted message
          const step = thinkingSteps.find((s) => s.id === stepId)
          let updatedConversation = currentConversation
          let updatedConversations = conversations

          if (step && currentConversation) {
            const updatedMessages = currentConversation.messages.map((msg) => {
              if (msg.id === step.userMessageId && msg.thinkingSteps) {
                return {
                  ...msg,
                  thinkingSteps: msg.thinkingSteps.map((s) =>
                    s.id === stepId ? { ...s, content: s.content + content } : s
                  ),
                }
              }
              return msg
            })

            updatedConversation = {
              ...currentConversation,
              messages: updatedMessages,
              updatedAt: new Date(),
            }

            updatedConversations = updateConversationInList(conversations, updatedConversation)
          }

          set(
            {
              thinkingSteps: updatedThinkingSteps,
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'appendToThinkingStep'
          )
        },

        completeThinkingStep: (stepId: string) => {
          const { currentConversation, conversations, thinkingSteps, activeThinkingStepId } = get()

          // Update ephemeral store
          const updatedThinkingSteps = thinkingSteps.map((step) =>
            step.id === stepId ? { ...step, isComplete: true } : step
          )

          // Find the userMessageId for this step to update persisted message
          const step = thinkingSteps.find((s) => s.id === stepId)
          let updatedConversation = currentConversation
          let updatedConversations = conversations

          if (step && currentConversation) {
            const updatedMessages = currentConversation.messages.map((msg) => {
              if (msg.id === step.userMessageId && msg.thinkingSteps) {
                return {
                  ...msg,
                  thinkingSteps: msg.thinkingSteps.map((s) =>
                    s.id === stepId ? { ...s, isComplete: true } : s
                  ),
                }
              }
              return msg
            })

            updatedConversation = {
              ...currentConversation,
              messages: updatedMessages,
              updatedAt: new Date(),
            }

            updatedConversations = updateConversationInList(conversations, updatedConversation)
          }

          set(
            {
              thinkingSteps: updatedThinkingSteps,
              activeThinkingStepId: activeThinkingStepId === stepId ? null : activeThinkingStepId,
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'completeThinkingStep'
          )
        },

        updateThinkingStepByFunctionName: (
          functionName: string,
          content: string,
          isComplete: boolean
        ) => {
          const { currentConversation, conversations, thinkingSteps, currentUserMessageId } = get()

          // Update ephemeral store
          const updatedThinkingSteps = thinkingSteps.map((step) =>
            step.functionName === functionName && step.userMessageId === currentUserMessageId ? { ...step, content, isComplete } : step
          )

          // Find the step to get its userMessageId for persistence
          const step = thinkingSteps.find((s) => s.functionName === functionName && s.userMessageId === currentUserMessageId)
          let updatedConversation = currentConversation
          let updatedConversations = conversations

          if (step && currentConversation) {
            const updatedMessages = currentConversation.messages.map((msg) => {
              if (msg.id === step.userMessageId && msg.thinkingSteps) {
                return {
                  ...msg,
                  thinkingSteps: msg.thinkingSteps.map((s) =>
                    s.functionName === functionName ? { ...s, content, isComplete } : s
                  ),
                }
              }
              return msg
            })

            updatedConversation = {
              ...currentConversation,
              messages: updatedMessages,
              updatedAt: new Date(),
            }

            updatedConversations = updateConversationInList(conversations, updatedConversation)
          }

          set(
            {
              thinkingSteps: updatedThinkingSteps,
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'updateThinkingStepByFunctionName'
          )
        },

        findThinkingStepByFunctionName: (functionName: string) => {
          const { thinkingSteps, currentUserMessageId } = get()
          if (!currentUserMessageId) return undefined
          return thinkingSteps.find(
            (step) =>
              step.functionName === functionName && step.userMessageId === currentUserMessageId
          )
        },

        setReportContent: (content: string, category?: 'research_notes' | 'final_report') => {
          set({ reportContent: content, reportContentCategory: category ?? null }, false, 'setReportContent')
        },

        clearThinkingSteps: () => {
          set({ thinkingSteps: [], activeThinkingStepId: null }, false, 'clearThinkingSteps')
        },

        clearReportContent: () => {
          set({ reportContent: '', reportContentCategory: null }, false, 'clearReportContent')
        },

        setCurrentStatus: (status: StatusType | null) => {
          set({ currentStatus: status }, false, 'setCurrentStatus')
        },

        addStatusCard: (type: StatusType, message?: string) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const statusMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: message || '',
            timestamp: new Date(),
            messageType: 'status',
            statusType: type,
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, statusMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
              currentStatus: type,
            },
            false,
            'addStatusCard'
          )
        },

        addAgentPrompt: (
          type: PromptType,
          content: string,
          options?: string[],
          placeholder?: string,
          promptId?: string,
          parentId?: string,
          inputType?: 'text' | 'multiple_choice' | 'binary_choice' | 'approval' | 'notification'
        ) => {
          const { currentConversation, conversations, planMessages } = get()
          if (!currentConversation) return

          const promptMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content,
            timestamp: new Date(),
            messageType: 'prompt',
            promptType: type,
            promptId,
            promptParentId: parentId,
            promptInputType: inputType,
            promptOptions: options,
            promptPlaceholder: placeholder,
            isPromptResponded: false,
            // Persist current planMessages for session restoration during HITL wait
            planMessages: planMessages.length > 0 ? [...planMessages] : undefined,
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, promptMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          // Pause streaming/loading while waiting for user response
          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
              isLoading: false,
              isStreaming: false,
            },
            false,
            'addAgentPrompt'
          )
        },

        respondToPrompt: (messageId: string, response: string) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const updatedMessages = currentConversation.messages.map((msg) =>
            msg.id === messageId
              ? { ...msg, promptResponse: response, isPromptResponded: true }
              : msg
          )

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
              isLoading: true, // Resume loading after user responds
              pendingInteraction: null, // Clear pending interaction
            },
            false,
            'respondToPrompt'
          )

          // NOTE: This only updates local state. To send the response to the backend,
          // the UI component or hook should call sendPromptResponse() from chat-client.ts
          // after this action completes. The backend integration depends on the
          // /generate/respond endpoint being implemented.
        },

        // ============================================================
        // Actions for agent responses and HITL
        // ============================================================

        addAgentResponse: (content: string, showViewReport?: boolean) => {
          const {
            currentConversation,
            conversations,
            reportContent,
            deepResearchCitations,
            planMessages,
            deepResearchTodos,
            deepResearchLLMSteps,
            deepResearchAgents,
            deepResearchToolCalls,
            deepResearchFiles,
            // Job persistence fields
            deepResearchJobId,
            deepResearchLastEventId,
            deepResearchStatus,
          } = get()
          if (!currentConversation) return

          // Include all ResearchPanel content for session persistence
          const responseMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content,
            timestamp: new Date(),
            messageType: 'agent_response',
            showViewReport,
            // Persist ResearchPanel content with this response
            reportContent: reportContent || undefined,
            citations: deepResearchCitations.length > 0 ? [...deepResearchCitations] : undefined,
            // Persist additional ResearchPanel tabs
            planMessages: planMessages.length > 0 ? [...planMessages] : undefined,
            deepResearchTodos: deepResearchTodos.length > 0 ? [...deepResearchTodos] : undefined,
            deepResearchLLMSteps: deepResearchLLMSteps.length > 0 ? [...deepResearchLLMSteps] : undefined,
            deepResearchAgents: deepResearchAgents.length > 0 ? [...deepResearchAgents] : undefined,
            deepResearchToolCalls: deepResearchToolCalls.length > 0 ? [...deepResearchToolCalls] : undefined,
            deepResearchFiles: deepResearchFiles.length > 0 ? [...deepResearchFiles] : undefined,
            // Persist deep research job metadata for session restoration
            deepResearchJobId: deepResearchJobId || undefined,
            deepResearchLastEventId: deepResearchLastEventId || undefined,
            deepResearchJobStatus: deepResearchStatus || undefined,
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, responseMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'addAgentResponse'
          )

          // Proactive storage check after response — this is when storage
          // meaningfully grows, not just on session create/switch.
          if (!checkStorageHealth().isHealthy) {
            const { currentUserId } = get()
            ensureStorageCapacity(currentConversation.id, currentUserId)
          }
        },

        addAgentResponseWithMeta: (
          content: string,
          showViewReport: boolean,
          meta: Partial<ChatMessage>
        ): string => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return ''

          const messageId = uuidv4()
          const responseMessage: ChatMessage = {
            id: messageId,
            role: 'assistant',
            content,
            timestamp: new Date(),
            messageType: 'agent_response',
            showViewReport,
            ...meta,
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, responseMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'addAgentResponseWithMeta'
          )

          return messageId
        },

        patchConversationMessage: (
          conversationId: string,
          messageId: string,
          patch: Partial<ChatMessage>
        ) => {
          const { currentConversation, conversations } = get()

          const targetConversation = conversations.find((c) => c.id === conversationId)
          if (!targetConversation) return

          const updatedMessages = targetConversation.messages.map((msg) =>
            msg.id === messageId ? { ...msg, ...patch } : msg
          )

          const updatedConversation: Conversation = {
            ...targetConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          const updatedCurrent =
            currentConversation?.id === conversationId
              ? updatedConversation
              : currentConversation

          set(
            {
              currentConversation: updatedCurrent,
              conversations: updatedConversations,
            },
            false,
            'patchConversationMessage'
          )
        },

        setPendingInteraction: (interaction: PendingInteraction | null) => {
          set({ pendingInteraction: interaction }, false, 'setPendingInteraction')
        },

        clearPendingInteraction: () => {
          set({ pendingInteraction: null }, false, 'clearPendingInteraction')
        },

        setRespondToInteractionFn: (fn) => {
          set({ respondToInteractionFn: fn }, false, 'setRespondToInteractionFn')
        },

        // ============================================================
        // Actions for file and error cards
        // ============================================================

        addFileCard: (data: FileCardData) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const fileMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: data.fileName,
            timestamp: new Date(),
            messageType: 'file',
            fileData: data,
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, fileMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'addFileCard'
          )
        },

        updateFileCard: (messageId: string, data: Partial<FileCardData>) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const updatedMessages = currentConversation.messages.map((msg) =>
            msg.id === messageId && msg.fileData
              ? {
                  ...msg,
                  fileData: { ...msg.fileData, ...data },
                  content: data.fileName || msg.content,
                }
              : msg
          )

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'updateFileCard'
          )
        },

        addErrorCard: (
          code: ErrorCode,
          message?: string,
          details?: string,
        ) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const errorMeta = getErrorMeta(code)

          const errorMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: message || errorMeta.defaultMessage,
            timestamp: new Date(),
            messageType: 'error',
            errorData: {
              errorCode: code,
              errorMessage: message,
              errorDetails: details,
            },
          }

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: [...currentConversation.messages, errorMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'addErrorCard'
          )
        },

        dismissErrorCard: (messageId: string) => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          // Remove the error message from the conversation
          const updatedMessages = currentConversation.messages.filter((msg) => msg.id !== messageId)

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'dismissErrorCard'
          )
        },

        dismissConnectionErrors: () => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          const updatedMessages = currentConversation.messages.filter(
            (msg) =>
              !(
                msg.messageType === 'error' &&
                msg.errorData?.errorCode?.startsWith('connection.')
              )
          )

          if (updatedMessages.length === currentConversation.messages.length) return

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'dismissConnectionErrors'
          )
        },

        // ============================================================
        // Actions for file upload status banners
        // ============================================================

        addFileUploadStatusCard: (
          type: FileUploadStatusType,
          fileCount: number,
          jobId: string,
          sessionId?: string
        ) => {
          const { currentConversation, conversations } = get()

          // Find target conversation: use sessionId if provided, otherwise currentConversation
          const targetConversation = sessionId
            ? conversations.find((c) => c.id === sessionId)
            : currentConversation

          if (!targetConversation) return

          const statusMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            messageType: 'file_upload_status',
            fileUploadStatusData: {
              type,
              fileCount,
              jobId,
            },
          }

          const updatedConversation: Conversation = {
            ...targetConversation,
            messages: [...targetConversation.messages, statusMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          // Only update currentConversation if we modified it
          const updatedCurrent =
            currentConversation?.id === targetConversation.id
              ? updatedConversation
              : currentConversation

          set(
            {
              currentConversation: updatedCurrent,
              conversations: updatedConversations,
            },
            false,
            'addFileUploadStatusCard'
          )
        },

        removeFileUploadWarning: () => {
          const { currentConversation, conversations } = get()
          if (!currentConversation) return

          // Remove all pending_warning file upload status messages from current conversation
          const updatedMessages = currentConversation.messages.filter(
            (msg) =>
              !(
                msg.messageType === 'file_upload_status' &&
                msg.fileUploadStatusData?.type === 'pending_warning'
              )
          )

          // Skip if nothing was removed
          if (updatedMessages.length === currentConversation.messages.length) return

          const updatedConversation: Conversation = {
            ...currentConversation,
            messages: updatedMessages,
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          set(
            {
              currentConversation: updatedConversation,
              conversations: updatedConversations,
            },
            false,
            'removeFileUploadWarning'
          )
        },

        // ============================================================
        // Actions for deep research banners
        // ============================================================

        addDeepResearchBanner: (
          bannerType: DeepResearchBannerType,
          jobId: string,
          conversationId?: string,
          stats?: { totalTokens?: number; toolCallCount?: number }
        ) => {
          const { currentConversation, conversations } = get()

          // Find target conversation: use conversationId if provided, otherwise currentConversation
          const targetConversation = conversationId
            ? conversations.find((c) => c.id === conversationId)
            : currentConversation

          if (!targetConversation) return

          // When adding a terminal banner, remove the 'starting' banner for the same job
          // to prevent stale "View Progress" buttons from persisting after completion
          const isTerminalBanner = bannerType !== 'starting'
          const filteredMessages = isTerminalBanner
            ? targetConversation.messages.filter(
                (m) =>
                  !(
                    m.messageType === 'deep_research_banner' &&
                    m.deepResearchBannerData?.bannerType === 'starting' &&
                    m.deepResearchBannerData?.jobId === jobId
                  )
              )
            : targetConversation.messages

          // Build banner message with job metadata for 'starting' banners
          // This supports session restoration and proper Cancel functionality
          const bannerMessage: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            messageType: 'deep_research_banner',
            deepResearchBannerData: {
              bannerType,
              jobId,
              totalTokens: stats?.totalTokens,
              toolCallCount: stats?.toolCallCount,
            },
            // For 'starting' banners, include job metadata for session restoration
            ...(bannerType === 'starting' && {
              deepResearchJobId: jobId,
              deepResearchJobStatus: 'submitted' as const,
              isDeepResearchActive: true,
            }),
          }

          const updatedConversation: Conversation = {
            ...targetConversation,
            messages: [...filteredMessages, bannerMessage],
            updatedAt: new Date(),
          }

          const updatedConversations = updateConversationInList(conversations, updatedConversation)

          // Only update currentConversation if we modified it
          const updatedCurrent =
            currentConversation?.id === targetConversation.id
              ? updatedConversation
              : currentConversation

          set(
            {
              currentConversation: updatedCurrent,
              conversations: updatedConversations,
            },
            false,
            'addDeepResearchBanner'
          )
        },

        // ============================================================
        // Actions for deep research SSE streaming
        // ============================================================

        startDeepResearch: (jobId: string, messageId?: string) => {
          const { currentConversation } = get()
          set(
            {
              deepResearchJobId: jobId,
              deepResearchLastEventId: null,
              isDeepResearchStreaming: true,
              deepResearchStatus: 'submitted',
              deepResearchOwnerConversationId: currentConversation?.id || null,
              activeDeepResearchMessageId: messageId || null,
              // Clear deep research execution content (but keep planMessages from planning phase)
              // planMessages are preserved to show the plan created during clarification
              reportContent: '',
              reportContentCategory: null,
              deepResearchCitations: [],
              deepResearchTodos: [],
              deepResearchLLMSteps: [],
              deepResearchAgents: [],
              deepResearchToolCalls: [],
              deepResearchFiles: [],
              deepResearchStreamLoaded: false,
            },
            false,
            'startDeepResearch'
          )
        },

        updateDeepResearchStatus: (status: DeepResearchJobStatus) => {
          set({ deepResearchStatus: status }, false, 'updateDeepResearchStatus')
        },

        completeDeepResearch: () => {
          const { deepResearchJobId } = get()
          // Clear sessionStorage since job is complete
          if (deepResearchJobId) {
            clearDeepResearchSession(deepResearchJobId)
          }
          set(
            {
              isDeepResearchStreaming: false,
              // Keep jobId, status, and citations for reference
            },
            false,
            'completeDeepResearch'
          )
        },

        addDeepResearchCitation: (url: string, content: string, isCited?: boolean) => {
          const { deepResearchCitations } = get()

          // Check if citation with same URL already exists
          const existingIndex = deepResearchCitations.findIndex((c) => c.url === url)

          if (existingIndex >= 0) {
            // Update existing citation - if it's being marked as cited, update that
            const updatedCitations = deepResearchCitations.map((c, i) => {
              if (i === existingIndex) {
                return {
                  ...c,
                  content: content || c.content,
                  // Once cited, always cited (citation_use trumps citation_source)
                  isCited: isCited || c.isCited,
                }
              }
              return c
            })

            set(
              { deepResearchCitations: updatedCitations },
              false,
              'addDeepResearchCitation:update'
            )
          } else {
            // Add new citation
            const newCitation: CitationSource = {
              id: uuidv4(),
              url,
              content,
              timestamp: new Date(),
              isCited,
            }

            set(
              {
                deepResearchCitations: [...deepResearchCitations, newCitation],
              },
              false,
              'addDeepResearchCitation'
            )
          }
        },

        setDeepResearchTodos: (todos: Array<{ content: string; status: string }>) => {
          // Convert raw todos to typed DeepResearchTodo items with generated IDs
          const typedTodos = todos.map((todo, index) => ({
            id: `todo-${index}-${todo.content.substring(0, 20).replace(/\s+/g, '-').toLowerCase()}`,
            content: todo.content,
            status: todo.status as 'pending' | 'in_progress' | 'completed' | 'stopped',
          }))

          set({ deepResearchTodos: typedTodos }, false, 'setDeepResearchTodos')
        },

        stopDeepResearchTodos: () => {
          const { deepResearchTodos } = get()
          const stoppedTodos = deepResearchTodos.map((todo) => ({
            ...todo,
            status:
              todo.status === 'in_progress' || todo.status === 'pending'
                ? ('stopped' as const)
                : todo.status,
          }))
          set({ deepResearchTodos: stoppedTodos }, false, 'stopDeepResearchTodos')
        },

        stopAllDeepResearchSpinners: (isSuccessfulCompletion = false) => {
          const {
            deepResearchTodos,
            deepResearchLLMSteps,
            deepResearchAgents,
            deepResearchToolCalls,
          } = get()

          // Stop todos (pending/in_progress → stopped or completed)
          const stoppedTodos = deepResearchTodos.map((todo) => ({
            ...todo,
            status:
              todo.status === 'in_progress' || todo.status === 'pending'
                ? (isSuccessfulCompletion ? ('completed' as const) : ('stopped' as const))
                : todo.status,
          }))

          // Complete LLM steps (mark incomplete ones as complete)
          const stoppedLLMSteps = deepResearchLLMSteps.map((step) => ({
            ...step,
            isComplete: true,
          }))

          // Stop agents (running → complete or error based on job success)
          const stoppedAgents = deepResearchAgents.map((agent) => ({
            ...agent,
            status: agent.status === 'running'
              ? (isSuccessfulCompletion ? ('complete' as const) : ('error' as const))
              : agent.status,
          }))

          // Stop tool calls (running → complete or error based on job success)
          const stoppedToolCalls = deepResearchToolCalls.map((toolCall) => ({
            ...toolCall,
            status: toolCall.status === 'running'
              ? (isSuccessfulCompletion ? ('complete' as const) : ('error' as const))
              : toolCall.status,
          }))

          set({
            deepResearchTodos: stoppedTodos,
            deepResearchLLMSteps: stoppedLLMSteps,
            deepResearchAgents: stoppedAgents,
            deepResearchToolCalls: stoppedToolCalls,
          }, false, 'stopAllDeepResearchSpinners')
        },

        clearDeepResearch: () => {
          set(
            {
              deepResearchJobId: null,
              deepResearchLastEventId: null,
              isDeepResearchStreaming: false,
              deepResearchStatus: null,
              deepResearchOwnerConversationId: null,
              activeDeepResearchMessageId: null,
              deepResearchCitations: [],
              deepResearchTodos: [],
              deepResearchLLMSteps: [],
              deepResearchAgents: [],
              deepResearchToolCalls: [],
              deepResearchFiles: [],
              deepResearchStreamLoaded: false,
            },
            false,
            'clearDeepResearch'
          )
        },

        setLoadedJobId: (jobId: string) => {
          set({ deepResearchJobId: jobId }, false, 'setLoadedJobId')
        },

        setStreamLoaded: (loaded: boolean) => {
          set({ deepResearchStreamLoaded: loaded }, false, 'setStreamLoaded')
        },

        setDeepResearchLastEventId: (eventId: string | null) => {
          set({ deepResearchLastEventId: eventId }, false, 'setDeepResearchLastEventId')
        },

        persistDeepResearchToSession: () => {
          const {
            deepResearchJobId,
            deepResearchLastEventId,
            deepResearchOwnerConversationId,
            activeDeepResearchMessageId,
            deepResearchStatus,
            isDeepResearchStreaming,
          } = get()

          // Only persist if there's an active streaming job
          if (!deepResearchJobId || !isDeepResearchStreaming) {
            return
          }

          saveDeepResearchToSession({
            jobId: deepResearchJobId,
            lastEventId: deepResearchLastEventId,
            ownerConversationId: deepResearchOwnerConversationId,
            activeMessageId: activeDeepResearchMessageId,
            status: deepResearchStatus,
          })
        },

        saveDeepResearchProgress: () => {
          const {
            currentConversation,
            isDeepResearchStreaming,
            deepResearchJobId,
            reportContent,
          } = get()

          // Only save if there's an active deep research session
          if (!currentConversation || !isDeepResearchStreaming || !deepResearchJobId) {
            return
          }

          // Save current progress by creating an agent response with all accumulated data
          // This persists: reportContent, citations, todos, LLM steps, agents, tool calls, files, and job metadata
          const statusMessage = reportContent
            ? 'Research in progress...'
            : 'Deep research started. Progress will be restored when you return.'
          get().addAgentResponse(statusMessage, !!reportContent)
        },

        reconnectToActiveJob: async () => {
          const { currentConversation, isDeepResearchStreaming } = get()
          if (!currentConversation || isDeepResearchStreaming) return

          const conversationId = currentConversation.id

          // Find messages with in-progress jobs (running or submitted)
          const activeJobMessage = [...currentConversation.messages]
            .reverse()
            .find((m) =>
              m.messageType === 'agent_response' &&
              m.deepResearchJobId &&
              m.isDeepResearchActive &&
              (m.deepResearchJobStatus === 'running' || m.deepResearchJobStatus === 'submitted')
            )

          if (!activeJobMessage?.deepResearchJobId) {
            return // No active job to reconnect
          }

          const jobId = activeJobMessage.deepResearchJobId
          const messageId = activeJobMessage.id

          try {
            const { getJobStatus } = await import('@/adapters/api/deep-research-client')

            // Verify conversation hasn't changed
            if (get().currentConversation?.id !== conversationId) return
            if (get().isDeepResearchStreaming) return

            const statusResponse = await getJobStatus(jobId)
            const currentStatus = statusResponse.status

            // Final check before setting state
            if (get().currentConversation?.id !== conversationId) return
            if (get().isDeepResearchStreaming) return

            if (currentStatus === 'running' || currentStatus === 'submitted') {
              // Start with empty arrays and null lastEventId to force a full SSE
              // replay from the beginning. The catch-up buffer collects all events
              // and flushes them to the store in a single setState call.
              set(
                {
                  deepResearchJobId: jobId,
                  deepResearchLastEventId: null,
                  isDeepResearchStreaming: true,
                  deepResearchStatus: currentStatus,
                  deepResearchOwnerConversationId: conversationId,
                  activeDeepResearchMessageId: messageId,
                  deepResearchCitations: [],
                  deepResearchTodos: [],
                  deepResearchLLMSteps: [],
                  deepResearchAgents: [],
                  deepResearchToolCalls: [],
                  deepResearchFiles: [],
                  deepResearchStreamLoaded: false,
                  reportContent: '',
                  reportContentCategory: null,
                  currentStatus: 'researching',
                },
                false,
                'reconnectToActiveJob'
              )
            } else {
              // Job completed while we were away - clear session storage and update message status
              clearDeepResearchSession(jobId)
              // Defensive cleanup: if sessionStorage restored items in 'running' state, fix them
              get().stopAllDeepResearchSpinners(currentStatus === 'success')
              get().patchConversationMessage(conversationId, messageId, {
                deepResearchJobStatus: currentStatus,
                isDeepResearchActive: false,
                showViewReport: currentStatus === 'success',
              })
              // Add terminal banner (also removes orphaned 'starting' banner for this job)
              const terminalBannerType: DeepResearchBannerType =
                currentStatus === 'success' ? 'success' : 'failure'
              get().addDeepResearchBanner(terminalBannerType, jobId, conversationId)
            }
          } catch (error) {
            console.warn('Failed to reconnect to active job:', error)
            if (isUnavailableDeepResearchJobError(error)) {
              clearDeepResearchSession(jobId)
              get().patchConversationMessage(conversationId, activeJobMessage.id, {
                deepResearchJobStatus: 'failure',
                isDeepResearchActive: false,
                showViewReport: Boolean(activeJobMessage.reportContent?.trim()),
              })
              get().addDeepResearchBanner('failure', jobId, conversationId)
            } else {
              // Mark as inactive to prevent retry loops
              get().patchConversationMessage(conversationId, activeJobMessage.id, {
                isDeepResearchActive: false,
              })
            }
          }

        },

        cleanupOrphanedStartingBanners: async () => {
          const { currentConversation } = get()
          if (!currentConversation) return

          const conversationId = currentConversation.id
          const syncTrackingMessageToTerminalState = (
            jobId: string,
            terminalStatus: DeepResearchJobStatus
          ): void => {
            const conversation = get().conversations.find((c) => c.id === conversationId)
            if (!conversation) return

            const trackingMessage = [...conversation.messages]
              .reverse()
              .find(
                (m) => m.messageType === 'agent_response' && m.deepResearchJobId === jobId
              )

            if (!trackingMessage?.id) return

            const hasPartialReport = Boolean(trackingMessage.reportContent?.trim())
            get().patchConversationMessage(conversationId, trackingMessage.id, {
              deepResearchJobStatus: terminalStatus,
              isDeepResearchActive: false,
              showViewReport: terminalStatus === 'success' || hasPartialReport,
            })
          }
          const bannerTypeToTerminalStatus = (
            bannerType: DeepResearchBannerType | undefined
          ): DeepResearchJobStatus => {
            // Preserve the distinction between explicit user cancellation and
            // terminal failures such as expiry/deletion. Cancelled jobs map to
            // the interrupted job status; backend lookup failures map to failure.
            if (bannerType === 'success') return 'success'
            if (bannerType === 'cancelled') return 'interrupted'
            return 'failure'
          }

          const startingBanners = currentConversation.messages.filter(
            (m) =>
              m.messageType === 'deep_research_banner' &&
              m.deepResearchBannerData?.bannerType === 'starting'
          )

          if (startingBanners.length === 0) return

          // Separate into banners with an existing terminal banner vs those needing a REST check
          const orphanedIds: string[] = []
          const needsCheck: Array<{ bannerId: string; jobId: string }> = []

          for (const banner of startingBanners) {
            const bannerJobId = banner.deepResearchBannerData!.jobId

            const matchingTerminalBanner = currentConversation.messages.find(
              (m) =>
                m.messageType === 'deep_research_banner' &&
                m.deepResearchBannerData?.jobId === bannerJobId &&
                m.id !== banner.id &&
                ['success', 'failure', 'cancelled'].includes(
                  m.deepResearchBannerData?.bannerType || ''
                )
            )

            if (matchingTerminalBanner) {
              const terminalStatus = bannerTypeToTerminalStatus(
                matchingTerminalBanner.deepResearchBannerData?.bannerType
              )
              syncTrackingMessageToTerminalState(bannerJobId, terminalStatus)
              orphanedIds.push(banner.id)
            } else {
              needsCheck.push({ bannerId: banner.id, jobId: bannerJobId })
            }
          }

          // Remove starting banners that already have a matching terminal banner
          if (orphanedIds.length > 0) {
            const conv = get().currentConversation
            if (conv && conv.id === conversationId) {
              const filtered = conv.messages.filter(
                (m) => !orphanedIds.includes(m.id)
              )
              const updatedConversation: Conversation = {
                ...conv,
                messages: filtered,
                updatedAt: new Date(),
              }
              const updatedConversations = updateConversationInList(
                get().conversations,
                updatedConversation
              )
              set(
                {
                  currentConversation: updatedConversation,
                  conversations: updatedConversations,
                },
                false,
                'cleanupOrphanedStartingBanners/removeOrphans'
              )
            }
          }

          // Poll REST API for remaining starting banners without a terminal counterpart
          if (needsCheck.length > 0) {
            try {
              const { getJobStatus } = await import(
                '@/adapters/api/deep-research-client'
              )
              for (const { jobId } of needsCheck) {
                // Bail out if conversation changed during async work
                if (get().currentConversation?.id !== conversationId) return
                try {
                  const statusResponse = await getJobStatus(jobId)
                  const terminalStatuses = ['success', 'failure', 'interrupted']
                  if (terminalStatuses.includes(statusResponse.status)) {
                    syncTrackingMessageToTerminalState(jobId, statusResponse.status)
                    const terminalType: DeepResearchBannerType =
                      statusResponse.status === 'success' ? 'success' : 'failure'
                    // addDeepResearchBanner removes the starting banner and adds the terminal one
                    get().addDeepResearchBanner(terminalType, jobId, conversationId)
                  }
                } catch (error) {
                  if (isUnavailableDeepResearchJobError(error)) {
                    clearDeepResearchSession(jobId)
                    syncTrackingMessageToTerminalState(jobId, 'failure')
                    get().addDeepResearchBanner('failure', jobId, conversationId)
                  }
                  // Other job check failures are likely transient — leave banner as-is
                }
              }
            } catch {
              // Module import failed — skip REST checks
            }
          }
        },

        // ============================================================
        // Actions for deep research ThinkingTab sub-tabs
        // ============================================================

        addDeepResearchLLMStep: (
          step: Omit<DeepResearchLLMStep, 'id' | 'timestamp' | 'isComplete'>
        ) => {
          const stepId = uuidv4()
          const newStep: DeepResearchLLMStep = {
            ...step,
            id: stepId,
            timestamp: new Date(),
            isComplete: false,
          }

          set(
            (state) => ({
              deepResearchLLMSteps: [...state.deepResearchLLMSteps, newStep],
            }),
            false,
            'addDeepResearchLLMStep'
          )

          return stepId
        },

        appendToDeepResearchLLMStep: (stepId: string, content: string) => {
          set(
            (state) => ({
              deepResearchLLMSteps: state.deepResearchLLMSteps.map((step) =>
                step.id === stepId ? { ...step, content: step.content + content } : step
              ),
            }),
            false,
            'appendToDeepResearchLLMStep'
          )
        },

        completeDeepResearchLLMStep: (
          stepId: string,
          thinking?: string,
          usage?: { input_tokens: number; output_tokens: number }
        ) => {
          set(
            (state) => ({
              deepResearchLLMSteps: state.deepResearchLLMSteps.map((step) =>
                step.id === stepId
                  ? { ...step, isComplete: true, thinking, usage }
                  : step
              ),
            }),
            false,
            'completeDeepResearchLLMStep'
          )
        },

        addDeepResearchAgent: (
          agent: Omit<DeepResearchAgent, 'id' | 'startedAt' | 'status'>
        ) => {
          const agentId = uuidv4()
          const newAgent: DeepResearchAgent = {
            ...agent,
            id: agentId,
            startedAt: new Date(),
            status: 'running',
          }

          set(
            (state) => ({
              deepResearchAgents: [...state.deepResearchAgents, newAgent],
            }),
            false,
            'addDeepResearchAgent'
          )

          return agentId
        },

        addDeepResearchAgentWithId: (
          id: string,
          agent: Omit<DeepResearchAgent, 'id' | 'startedAt' | 'status'>
        ) => {
          const { deepResearchAgents } = get()

          if (deepResearchAgents.some((a) => a.id === id)) {
            return id
          }

          const newAgent: DeepResearchAgent = {
            ...agent,
            id,
            startedAt: new Date(),
            status: 'running',
          }

          set(
            (state) => ({
              deepResearchAgents: [...state.deepResearchAgents, newAgent],
            }),
            false,
            'addDeepResearchAgentWithId'
          )

          return id
        },

        completeDeepResearchAgent: (agentId: string, output?: string) => {
          set(
            (state) => ({
              deepResearchAgents: state.deepResearchAgents.map((agent) =>
                agent.id === agentId
                  ? { ...agent, status: 'complete' as const, output, completedAt: new Date() }
                  : agent
              ),
            }),
            false,
            'completeDeepResearchAgent'
          )
        },

        addDeepResearchToolCall: (
          toolCall: Omit<DeepResearchToolCall, 'id' | 'timestamp' | 'status'>
        ) => {
          const toolCallId = uuidv4()
          const newToolCall: DeepResearchToolCall = {
            ...toolCall,
            id: toolCallId,
            timestamp: new Date(),
            status: 'running',
          }

          set(
            (state) => ({
              deepResearchToolCalls: [...state.deepResearchToolCalls, newToolCall],
            }),
            false,
            'addDeepResearchToolCall'
          )

          return toolCallId
        },

        getAgentToolCalls: (agentId: string) => {
          const { deepResearchToolCalls } = get()
          return deepResearchToolCalls.filter((tc) => tc.agentId === agentId)
        },

        completeDeepResearchToolCall: (toolCallId: string, output?: string) => {
          set(
            (state) => ({
              deepResearchToolCalls: state.deepResearchToolCalls.map((toolCall) =>
                toolCall.id === toolCallId
                  ? { ...toolCall, status: 'complete' as const, output }
                  : toolCall
              ),
            }),
            false,
            'completeDeepResearchToolCall'
          )
        },

        addDeepResearchFile: (file: Omit<DeepResearchFile, 'id' | 'timestamp'>) => {
          const { deepResearchFiles } = get()
          const existingIndex = deepResearchFiles.findIndex((f) => f.filename === file.filename)

          if (existingIndex >= 0) {
            // Update existing file with latest content
            const updatedFiles = deepResearchFiles.map((f, i) =>
              i === existingIndex
                ? { ...f, content: file.content, timestamp: new Date() }
                : f
            )
            set({ deepResearchFiles: updatedFiles }, false, 'addDeepResearchFile:update')
            return deepResearchFiles[existingIndex].id
          }

          const fileId = uuidv4()
          const newFile: DeepResearchFile = {
            ...file,
            id: fileId,
            timestamp: new Date(),
          }

          set(
            (state) => ({
              deepResearchFiles: [...state.deepResearchFiles, newFile],
            }),
            false,
            'addDeepResearchFile'
          )

          return fileId
        },

        // ============================================================
        // Actions for PlanTab messages
        // ============================================================

        addPlanMessage: (message: Omit<PlanMessage, 'id' | 'timestamp'>) => {
          const messageId = uuidv4()
          const newMessage: PlanMessage = {
            ...message,
            id: messageId,
            timestamp: new Date(),
          }

          set(
            (state) => ({
              planMessages: [...state.planMessages, newMessage],
            }),
            false,
            'addPlanMessage'
          )

          // Persist planMessages for HITL recovery on page refresh
          get().persistPlanMessages()

          return messageId
        },

        updatePlanMessageResponse: (messageId: string, response: string) => {
          set(
            (state) => ({
              planMessages: state.planMessages.map((msg) =>
                msg.id === messageId ? { ...msg, userResponse: response } : msg
              ),
            }),
            false,
            'updatePlanMessageResponse'
          )

          // Persist planMessages for HITL recovery on page refresh
          get().persistPlanMessages()
        },

        clearPlanMessages: () => {
          set({ planMessages: [] }, false, 'clearPlanMessages')
        },

        persistPlanMessages: () => {
          const { currentConversation, conversations, planMessages } = get()
          if (!currentConversation || planMessages.length === 0) return

          // Find the most recent unresponded prompt message to attach planMessages to
          // This ensures planMessages survive page refresh during HITL flows
          const messages = currentConversation.messages
          const lastPromptIndex = [...messages]
            .reverse()
            .findIndex((m) => m.messageType === 'prompt' && !m.isPromptResponded)

          if (lastPromptIndex >= 0) {
            const actualIndex = messages.length - 1 - lastPromptIndex
            const updatedMessages = messages.map((msg, idx) =>
              idx === actualIndex
                ? { ...msg, planMessages: [...planMessages] }
                : msg
            )

            const updatedConversation: Conversation = {
              ...currentConversation,
              messages: updatedMessages,
              updatedAt: new Date(),
            }

            const updatedConversations = updateConversationInList(conversations, updatedConversation)

            set(
              {
                currentConversation: updatedConversation,
                conversations: updatedConversations,
              },
              false,
              'persistPlanMessages'
            )
          }
        },

        // ============================================================
        // Session restoration
        // ============================================================

        restoreSessionState: (conversation: Conversation) => {
          // Aggregate thinkingSteps from all user messages in the conversation
          const allSteps = conversation.messages
            .filter((m) => m.thinkingSteps && m.thinkingSteps.length > 0)
            .flatMap((m) => m.thinkingSteps!)

          // Get latest ResearchPanel content from last agent_response message
          const lastAgentResponse = [...conversation.messages]
            .reverse()
            .find((m) => m.messageType === 'agent_response')

          // Check for unresponded HITL prompt to restore pendingInteraction
          const unrespondedPrompt = [...conversation.messages]
            .reverse()
            .find((m) => m.messageType === 'prompt' && !m.isPromptResponded)

          let restoredPendingInteraction: PendingInteraction | null = null
          if (unrespondedPrompt?.promptId && unrespondedPrompt?.promptParentId && unrespondedPrompt?.promptInputType) {
            restoredPendingInteraction = {
              id: unrespondedPrompt.promptId,
              parentId: unrespondedPrompt.promptParentId,
              inputType: unrespondedPrompt.promptInputType,
              text: unrespondedPrompt.content,
              options: unrespondedPrompt.promptOptions,
            }
          }

          // Restore planMessages from unresponded prompt (during HITL wait) or last agent response
          const restoredPlanMessages = unrespondedPrompt?.planMessages || lastAgentResponse?.planMessages || []

          // NOTE: Heavy research data fields are NO LONGER restored from localStorage
          // They were removed by pruneMessageForStorage to save space (~96% reduction)
          // Research data will be fetched from backend on-demand via importStreamOnly()
          // when user opens ResearchPanel tabs or clicks "View Report"

          set(
            {
              thinkingSteps: allSteps,
              activeThinkingStepId: null,
              // DO NOT restore heavy research data - will be fetched from backend on demand
              reportContent: '',
              reportContentCategory: null,
              deepResearchCitations: [],
              deepResearchTodos: [],
              deepResearchLLMSteps: [],
              deepResearchAgents: [],
              deepResearchToolCalls: [],
              deepResearchFiles: [],
              // ONLY restore planMessages - cannot be fetched from backend (WebSocket only)
              planMessages: restoredPlanMessages,
              // Clear streaming/loading state for restored sessions
              // In-progress jobs will reconnect via reconnectToActiveJob
              isStreaming: false,
              isLoading: false,
              currentStatus: null,
              // Restore pending HITL interaction from unresponded prompt message
              pendingInteraction: restoredPendingInteraction,
              // Restore job ID so research data can be fetched on demand
              deepResearchJobId: lastAgentResponse?.deepResearchJobId || null,
              deepResearchLastEventId: null,
              isDeepResearchStreaming: false,
              deepResearchStatus: null,
              activeDeepResearchMessageId: lastAgentResponse?.id || null,
              deepResearchOwnerConversationId: conversation.id,
              // Set to false to trigger lazy loading when tabs are opened
              deepResearchStreamLoaded: false,
            },
            false,
            'restoreSessionState'
          )

          // Detect interrupted responses: if the last meaningful message is a user
          // message with thinking steps but no following response, the response was
          // interrupted by a page refresh or browser close mid-stream.
          // Skip if there's a pending HITL interaction (user is expected to respond).
          if (!restoredPendingInteraction) {
            const meaningfulTypes = new Set(['user', 'assistant', 'agent_response', 'error', 'prompt'])
            const lastMeaningful = [...conversation.messages]
              .reverse()
              .find((m) => meaningfulTypes.has(m.messageType ?? ''))

            if (lastMeaningful?.messageType === 'user' && lastMeaningful.thinkingSteps?.length) {
              get().addErrorCard(
                'agent.response_interrupted',
                'Your previous request was not completed. Please resend your message.'
              )
            }
          }
        },

        // ============================================================
        // Session busy checks (for disabling UI controls)
        // ============================================================

        /**
         * Check if a specific session has active operations.
         * MUST scan message history because ephemeral state is cleared on session switch.
         *
         * @param conversationId - The conversation ID to check
         * @returns true if the session has active operations (shallow or deep research)
         */
        isSessionBusy: (conversationId: string) => {
          const state = get()

          // Check if this is the current session with active shallow thinking (WebSocket)
          if (state.currentConversation?.id === conversationId && state.isStreaming) {
            return true
          }

          // Check if this is the currently streaming deep research session (ephemeral check)
          if (
            state.deepResearchOwnerConversationId === conversationId &&
            state.isDeepResearchStreaming
          ) {
            return true
          }

          // CRITICAL: Check message history for background deep research jobs
          // This is the ONLY way to detect jobs in non-current sessions
          // Uses shared utility that scans from end for O(1) typical performance
          const conversation = state.conversations.find((c) => c.id === conversationId)
          if (conversation && hasActiveDeepResearchJob(conversation.messages)) {
            return true
          }

          return false
        },

        /**
         * Check if ANY session has active operations.
         * Used to disable "Delete All Sessions" button.
         *
         * @returns true if any session has active operations
         */
        hasAnyBusySession: () => {
          const state = get()
          // Check global pending interaction (persisted, survives refresh)
          if (state.pendingInteraction !== null) return true
          return state.conversations.some((conv) => state.isSessionBusy(conv.id))
        },
      }),
      {
        name: 'aiq-chat-store',
        storage: typeof window === 'undefined' ? undefined : createResilientStorage(),
        partialize: (state) => ({
          // Persist conversations and user context, not streaming state or panel content
          currentUserId: state.currentUserId,
          conversations: state.conversations,
          currentConversation: state.currentConversation,
          // Persist pending HITL interaction for page refresh recovery
          pendingInteraction: state.pendingInteraction,
        }),
      }
    ),
    { name: 'ChatStore' }
  )
)

// ============================================================
// Selectors
// ============================================================

export const selectHasConnectionError = (state: ChatStore): boolean =>
  state.currentConversation?.messages.some(
    (m) =>
      m.messageType === 'error' &&
      m.errorData?.errorCode?.startsWith('connection.')
  ) ?? false

// ============================================================
// Storage Event Monitoring (for debugging session clearing)
// ============================================================

if (typeof window !== 'undefined') {
  // Log initial hydration state (dev-only)
  const initialState = useChatStore.getState()
  logStoreHydration(
    true,
    initialState.conversations?.length ?? 0,
    initialState.currentUserId
  )

  // Monitor storage events from other tabs or browser extensions
  window.addEventListener('storage', (event) => {
    // Only log events related to our chat store
    if (event.key === 'aiq-chat-store') {
      logExternalStorageEvent(event.key, event.oldValue, event.newValue)

      // If the store was cleared externally, this is critical
      if (event.oldValue !== null && event.newValue === null) {
        console.error(
          '[SessionsStore] ❌ CRITICAL: Storage cleared by external source (browser extension, dev tools, or another tab)'
        )
      }
    }
  })
}
