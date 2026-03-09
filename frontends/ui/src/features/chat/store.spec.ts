// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest'
import { useChatStore } from './store'
import type { Conversation, PendingInteraction, FileCardData } from './types'

const STORAGE_KEY = 'aiq-chat-store'
const mockLayoutState = vi.hoisted(() => ({
  closeRightPanel: vi.fn(),
  enabledDataSourceIds: ['web_search'],
  availableDataSources: [{ id: 'web_search' }, { id: 'knowledge_base' }],
  setEnabledDataSources: vi.fn(),
}))
const mockDeepResearchApi = vi.hoisted(() => ({
  getJobStatus: vi.fn(),
  cancelJob: vi.fn(),
}))

// Mock the layout store
vi.mock('@/features/layout/store', () => ({
  useLayoutStore: {
    getState: () => mockLayoutState,
  },
}))

vi.mock('@/adapters/api/deep-research-client', () => ({
  getJobStatus: mockDeepResearchApi.getJobStatus,
  cancelJob: mockDeepResearchApi.cancelJob,
}))

describe('useChatStore', () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.removeItem(STORAGE_KEY)
    mockLayoutState.closeRightPanel.mockClear()
    mockLayoutState.setEnabledDataSources.mockClear()
    mockLayoutState.enabledDataSourceIds = ['web_search']
    mockLayoutState.availableDataSources = [{ id: 'web_search' }, { id: 'knowledge_base' }]
    mockDeepResearchApi.getJobStatus.mockReset()
    mockDeepResearchApi.cancelJob.mockReset()
    // Reset store to initial state before each test
    useChatStore.setState({
      currentUserId: null,
      currentConversation: null,
      conversations: [],
      isStreaming: false,
      isLoading: false,
      currentUserMessageId: null,
      thinkingSteps: [],
      activeThinkingStepId: null,
      reportContent: '',
      currentStatus: null,
      pendingInteraction: null,
    })
  })

  afterEach(() => {
    // Clean up localStorage after each test
    localStorage.removeItem(STORAGE_KEY)
  })

  describe('initial state', () => {
    test('has correct default values', () => {
      const state = useChatStore.getState()

      expect(state.currentUserId).toBeNull()
      expect(state.currentConversation).toBeNull()
      expect(state.conversations).toEqual([])
      expect(state.isStreaming).toBe(false)
      expect(state.isLoading).toBe(false)
      expect(state.currentUserMessageId).toBeNull()
      expect(state.thinkingSteps).toEqual([])
      expect(state.activeThinkingStepId).toBeNull()
      expect(state.reportContent).toBe('')
      expect(state.currentStatus).toBeNull()
      expect(state.pendingInteraction).toBeNull()
    })
  })

  describe('setCurrentUser', () => {
    test('sets user ID', () => {
      useChatStore.getState().setCurrentUser('user-1')

      expect(useChatStore.getState().currentUserId).toBe('user-1')
    })

    test('clears thinking state when user changes', () => {
      useChatStore.setState({
        currentUserId: 'user-1',
        currentUserMessageId: 'msg-1',
        thinkingSteps: [
          {
            id: '1',
            userMessageId: 'msg-1',
            category: 'agents',
            functionName: 'test',
            displayName: 'Test',
            content: '',
            timestamp: new Date(),
            isComplete: false,
          },
        ],
        activeThinkingStepId: '1',
        reportContent: 'Some report',
        currentStatus: 'thinking',
      })

      useChatStore.getState().setCurrentUser('user-2')

      const state = useChatStore.getState()
      expect(state.thinkingSteps).toEqual([])
      expect(state.activeThinkingStepId).toBeNull()
      expect(state.reportContent).toBe('')
      expect(state.currentStatus).toBeNull()
    })

    test('auto-selects first conversation for new user', () => {
      const conv1: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Conv 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      const conv2: Conversation = {
        id: 'conv-2',
        userId: 'user-2',
        title: 'Conv 2',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv1,
        conversations: [conv1, conv2],
      })

      useChatStore.getState().setCurrentUser('user-2')

      expect(useChatStore.getState().currentConversation).toEqual(conv2)
      expect(mockLayoutState.setEnabledDataSources).toHaveBeenCalledWith(['web_search'])
    })

    test('clears current conversation when logging out', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Conv 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })

      useChatStore.getState().setCurrentUser(null)

      expect(useChatStore.getState().currentConversation).toBeNull()
    })
  })

  describe('getUserConversations', () => {
    test('returns empty array when no user', () => {
      useChatStore.setState({
        currentUserId: null,
        conversations: [
          {
            id: 'conv-1',
            userId: 'user-1',
            title: 'Conv',
            messages: [],
            createdAt: new Date(),
            updatedAt: new Date(),
          },
        ],
      })

      expect(useChatStore.getState().getUserConversations()).toEqual([])
    })

    test('returns only conversations for current user', () => {
      const conv1: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'User 1 Conv',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      const conv2: Conversation = {
        id: 'conv-2',
        userId: 'user-2',
        title: 'User 2 Conv',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        currentUserId: 'user-1',
        conversations: [conv1, conv2],
      })

      const result = useChatStore.getState().getUserConversations()

      expect(result).toHaveLength(1)
      expect(result[0].id).toBe('conv-1')
    })
  })

  describe('createConversation', () => {
    test('creates new conversation for current user', () => {
      useChatStore.setState({ currentUserId: 'user-1' })

      const conv = useChatStore.getState().createConversation()

      expect(conv.userId).toBe('user-1')
      expect(conv.title).toBe('New Session')
      expect(conv.messages).toEqual([])
      expect(useChatStore.getState().currentConversation).toEqual(conv)
      expect(useChatStore.getState().conversations).toContainEqual(conv)
    })

    test('throws when no user is authenticated', () => {
      expect(() => useChatStore.getState().createConversation()).toThrow(
        'Cannot create conversation without authenticated user'
      )
    })

    test('clears thinking state on new conversation', () => {
      useChatStore.setState({
        currentUserId: 'user-1',
        thinkingSteps: [
          {
            id: '1',
            userMessageId: 'msg-1',
            category: 'agents',
            functionName: 'test',
            displayName: 'Test',
            content: '',
            timestamp: new Date(),
            isComplete: false,
          },
        ],
        reportContent: 'Old report',
      })

      useChatStore.getState().createConversation()

      const state = useChatStore.getState()
      expect(state.thinkingSteps).toEqual([])
      expect(state.reportContent).toBe('')
    })
  })

  describe('ensureSession', () => {
    test('returns existing conversation ID', () => {
      const conv: Conversation = {
        id: 'existing-conv',
        userId: 'user-1',
        title: 'Existing',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({ currentUserId: 'user-1', currentConversation: conv })

      const result = useChatStore.getState().ensureSession()

      expect(result).toBe('existing-conv')
    })

    test('creates new conversation if none exists', () => {
      useChatStore.setState({ currentUserId: 'user-1', currentConversation: null })

      const result = useChatStore.getState().ensureSession()

      expect(result).toBeDefined()
      expect(useChatStore.getState().currentConversation).not.toBeNull()
    })

    test('returns undefined when no user', () => {
      useChatStore.setState({ currentUserId: null, currentConversation: null })

      const result = useChatStore.getState().ensureSession()

      expect(result).toBeUndefined()
    })
  })

  describe('selectConversation', () => {
    test('selects conversation owned by current user', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Conv 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        conversations: [conv],
        currentConversation: null,
      })

      useChatStore.getState().selectConversation('conv-1')

      expect(useChatStore.getState().currentConversation).toEqual(conv)
    })

    test('does not select conversation owned by different user', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-2',
        title: 'Conv 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        conversations: [conv],
        currentConversation: null,
      })

      useChatStore.getState().selectConversation('conv-1')

      expect(useChatStore.getState().currentConversation).toBeNull()
    })

    test('clears thinking state on selection', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Conv',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        conversations: [conv],
        thinkingSteps: [
          {
            id: '1',
            userMessageId: 'msg-1',
            category: 'agents',
            functionName: 'test',
            displayName: 'Test',
            content: '',
            timestamp: new Date(),
            isComplete: false,
          },
        ],
        reportContent: 'Old',
      })

      useChatStore.getState().selectConversation('conv-1')

      expect(useChatStore.getState().thinkingSteps).toEqual([])
      expect(useChatStore.getState().reportContent).toBe('')
    })
  })

  describe('addUserMessage', () => {
    test('adds user message to current conversation', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'New Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })

      const msg = useChatStore.getState().addUserMessage('Hello')

      expect(msg.role).toBe('user')
      expect(msg.content).toBe('Hello')
      expect(useChatStore.getState().currentConversation?.messages).toHaveLength(1)
    })

    test('updates title on first message', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'New Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })

      useChatStore.getState().addUserMessage('What is the capital of France?')

      expect(useChatStore.getState().currentConversation?.title).toBe(
        'What is the capital of France?'
      )
    })

    test('truncates long titles to 50 characters', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'New Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })

      const longMessage = 'A'.repeat(100)
      useChatStore.getState().addUserMessage(longMessage)

      expect(useChatStore.getState().currentConversation?.title).toBe('A'.repeat(50) + '...')
    })

    test('creates conversation if none exists', () => {
      mockLayoutState.enabledDataSourceIds = ['web_search', 'knowledge_base']
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: null,
        conversations: [],
      })

      useChatStore.getState().addUserMessage('Hello')

      expect(useChatStore.getState().currentConversation).not.toBeNull()
      expect(useChatStore.getState().conversations).toHaveLength(1)
      expect(useChatStore.getState().currentConversation?.enabledDataSourceIds).toEqual([
        'web_search',
        'knowledge_base',
      ])
    })

    test('throws when no user authenticated', () => {
      useChatStore.setState({ currentUserId: null, currentConversation: null })

      expect(() => useChatStore.getState().addUserMessage('Hello')).toThrow(
        'Cannot create conversation without authenticated user'
      )
    })

    test('sets loading state and updates currentUserMessageId', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'New Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
        currentUserMessageId: 'old-msg-id',
        thinkingSteps: [
          {
            id: '1',
            userMessageId: 'old-msg-id',
            category: 'agents',
            functionName: 'test',
            displayName: 'Test',
            content: '',
            timestamp: new Date(),
            isComplete: false,
          },
        ],
      })

      const message = useChatStore.getState().addUserMessage('Hello')

      expect(useChatStore.getState().isLoading).toBe(true)
      // New behavior: thinking steps are preserved (associated with previous message)
      expect(useChatStore.getState().thinkingSteps).toHaveLength(1)
      // currentUserMessageId is updated to the new message
      expect(useChatStore.getState().currentUserMessageId).toBe(message.id)
    })
  })

  describe('assistant message streaming', () => {
    const setupConversation = () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })
      return conv
    }

    test('startAssistantMessage creates streaming message', () => {
      setupConversation()

      const msg = useChatStore.getState().startAssistantMessage()

      expect(msg.role).toBe('assistant')
      expect(msg.content).toBe('')
      expect(msg.isStreaming).toBe(true)
      expect(useChatStore.getState().isStreaming).toBe(true)
      expect(useChatStore.getState().isLoading).toBe(false)
    })

    test('startAssistantMessage throws when no conversation', () => {
      useChatStore.setState({ currentConversation: null })

      expect(() => useChatStore.getState().startAssistantMessage()).toThrow(
        'No active conversation'
      )
    })

    test('appendToAssistantMessage appends to streaming message', () => {
      setupConversation()
      useChatStore.getState().startAssistantMessage()

      useChatStore.getState().appendToAssistantMessage('Hello ')
      useChatStore.getState().appendToAssistantMessage('world!')

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages?.[0].content).toBe('Hello world!')
    })

    test('appendToAssistantMessage does nothing if no streaming message', () => {
      setupConversation()

      useChatStore.getState().appendToAssistantMessage('Hello')

      expect(useChatStore.getState().currentConversation?.messages).toHaveLength(0)
    })

    test('completeAssistantMessage marks message as complete', () => {
      setupConversation()
      useChatStore.getState().startAssistantMessage()
      useChatStore.getState().appendToAssistantMessage('Response')

      useChatStore.getState().completeAssistantMessage()

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages?.[0].isStreaming).toBe(false)
      expect(useChatStore.getState().isStreaming).toBe(false)
    })
  })

  describe('loading state', () => {
    test('setLoading sets loading state', () => {
      useChatStore.getState().setLoading(true)
      expect(useChatStore.getState().isLoading).toBe(true)

      useChatStore.getState().setLoading(false)
      expect(useChatStore.getState().isLoading).toBe(false)
    })

    test('setStreaming sets streaming state', () => {
      useChatStore.getState().setStreaming(true)
      expect(useChatStore.getState().isStreaming).toBe(true)

      useChatStore.getState().setStreaming(false)
      expect(useChatStore.getState().isStreaming).toBe(false)
    })
  })

  describe('conversation management', () => {
    test('deleteConversation removes conversation', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({ currentConversation: conv, conversations: [conv] })

      useChatStore.getState().deleteConversation('conv-1')

      expect(useChatStore.getState().conversations).toHaveLength(0)
      expect(useChatStore.getState().currentConversation).toBeNull()
    })

    test('deleteConversation keeps current if different', () => {
      const conv1: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      const conv2: Conversation = {
        id: 'conv-2',
        userId: 'user-1',
        title: 'Test 2',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({ currentConversation: conv1, conversations: [conv1, conv2] })

      useChatStore.getState().deleteConversation('conv-2')

      expect(useChatStore.getState().currentConversation).toEqual(conv1)
    })

    test('deleteConversation removes session from localStorage', async () => {
      // Create conversations and wait for persist
      const conv1: Conversation = {
        id: 'conv-persist-1',
        userId: 'user-1',
        title: 'Session to Delete',
        messages: [],
        createdAt: new Date('2024-01-01'),
        updatedAt: new Date('2024-01-01'),
      }
      const conv2: Conversation = {
        id: 'conv-persist-2',
        userId: 'user-1',
        title: 'Session to Keep',
        messages: [],
        createdAt: new Date('2024-01-02'),
        updatedAt: new Date('2024-01-02'),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv1,
        conversations: [conv1, conv2],
      })

      // Wait for Zustand persist to sync to localStorage
      await vi.waitFor(() => {
        const stored = localStorage.getItem(STORAGE_KEY)
        expect(stored).not.toBeNull()
        const parsed = JSON.parse(stored!)
        expect(parsed.state.conversations).toHaveLength(2)
      })

      // Verify initial localStorage state
      const beforeDelete = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
      expect(beforeDelete.state.conversations.map((c: Conversation) => c.id)).toContain(
        'conv-persist-1'
      )
      expect(beforeDelete.state.conversations.map((c: Conversation) => c.id)).toContain(
        'conv-persist-2'
      )

      // Delete the first conversation
      useChatStore.getState().deleteConversation('conv-persist-1')

      // Wait for Zustand persist to sync the deletion to localStorage
      await vi.waitFor(() => {
        const stored = localStorage.getItem(STORAGE_KEY)
        const parsed = JSON.parse(stored!)
        expect(parsed.state.conversations).toHaveLength(1)
      })

      // Verify localStorage was updated correctly
      const afterDelete = JSON.parse(localStorage.getItem(STORAGE_KEY)!)

      // The deleted session should NOT be in localStorage
      expect(afterDelete.state.conversations.map((c: Conversation) => c.id)).not.toContain(
        'conv-persist-1'
      )

      // The other session should still be in localStorage
      expect(afterDelete.state.conversations.map((c: Conversation) => c.id)).toContain(
        'conv-persist-2'
      )

      // currentConversation should be cleared since we deleted the current one
      expect(afterDelete.state.currentConversation).toBeNull()
    })

    test('deleteConversation updates currentConversation in localStorage when deleting current', async () => {
      const conv: Conversation = {
        id: 'conv-current',
        userId: 'user-1',
        title: 'Current Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })

      // Wait for initial persist (currentConversation stored as ID string)
      await vi.waitFor(() => {
        const stored = localStorage.getItem(STORAGE_KEY)
        expect(stored).not.toBeNull()
        const parsed = JSON.parse(stored!)
        expect(parsed.state.currentConversation).toBe('conv-current')
      })

      // Delete the current conversation
      useChatStore.getState().deleteConversation('conv-current')

      // Wait for persist to sync
      await vi.waitFor(() => {
        const stored = localStorage.getItem(STORAGE_KEY)
        const parsed = JSON.parse(stored!)
        expect(parsed.state.conversations).toHaveLength(0)
      })

      // Verify currentConversation is cleared in localStorage
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
      expect(stored.state.currentConversation).toBeNull()
      expect(stored.state.conversations).toHaveLength(0)
    })

    test('updateConversationTitle updates title', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Old Title',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({ currentConversation: conv, conversations: [conv] })

      useChatStore.getState().updateConversationTitle('conv-1', 'New Title')

      expect(useChatStore.getState().currentConversation?.title).toBe('New Title')
      expect(useChatStore.getState().conversations[0].title).toBe('New Title')
    })
  })

  describe('thinking steps', () => {
    // Helper to set up a user message context for thinking steps tests
    const setupUserMessageContext = () => {
      useChatStore.getState().setCurrentUser('test-user')
      const message = useChatStore.getState().addUserMessage('Test message')
      return message.id
    }

    test('addThinkingStep adds step and returns ID', () => {
      const userMessageId = setupUserMessageContext()

      const stepId = useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'intent_classifier',
        displayName: 'Intent Classifier',
        content: 'Initial thought',
        isComplete: false,
      })

      expect(stepId).toBeDefined()
      const steps = useChatStore.getState().thinkingSteps
      expect(steps).toHaveLength(1)
      expect(steps[0].category).toBe('agents')
      expect(steps[0].functionName).toBe('intent_classifier')
      expect(steps[0].displayName).toBe('Intent Classifier')
      expect(steps[0].content).toBe('Initial thought')
      expect(steps[0].isComplete).toBe(false)
      expect(steps[0].userMessageId).toBe(userMessageId)
      expect(useChatStore.getState().activeThinkingStepId).toBe(stepId)
    })

    test('addThinkingStep returns empty string without currentUserMessageId', () => {
      // Don't set up user message context
      const stepId = useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'test',
        displayName: 'Test',
        content: '',
        isComplete: false,
      })

      expect(stepId).toBe('')
      expect(useChatStore.getState().thinkingSteps).toHaveLength(0)
    })

    test('appendToThinkingStep appends content', () => {
      setupUserMessageContext()

      const stepId = useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'test_agent',
        displayName: 'Test Agent',
        content: 'Hello ',
        isComplete: false,
      })

      useChatStore.getState().appendToThinkingStep(stepId, 'world!')

      expect(useChatStore.getState().thinkingSteps[0].content).toBe('Hello world!')
    })

    test('completeThinkingStep marks step complete', () => {
      setupUserMessageContext()

      const stepId = useChatStore.getState().addThinkingStep({
        category: 'tasks',
        functionName: '<workflow>',
        displayName: 'Workflow',
        content: '',
        isComplete: false,
      })

      useChatStore.getState().completeThinkingStep(stepId)

      expect(useChatStore.getState().thinkingSteps[0].isComplete).toBe(true)
      expect(useChatStore.getState().activeThinkingStepId).toBeNull()
    })

    test('clearThinkingSteps clears all steps', () => {
      setupUserMessageContext()

      useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'agent1',
        displayName: 'Agent 1',
        content: '',
        isComplete: false,
      })
      useChatStore.getState().addThinkingStep({
        category: 'tools',
        functionName: 'web_search_tool',
        displayName: 'Web Search Tool',
        content: '',
        isComplete: false,
      })

      useChatStore.getState().clearThinkingSteps()

      expect(useChatStore.getState().thinkingSteps).toEqual([])
      expect(useChatStore.getState().activeThinkingStepId).toBeNull()
    })

    test('updateThinkingStepByFunctionName updates step', () => {
      setupUserMessageContext()

      useChatStore.getState().addThinkingStep({
        category: 'tools',
        functionName: 'web_search_tool',
        displayName: 'Web Search Tool',
        content: 'Searching...',
        isComplete: false,
      })

      useChatStore.getState().updateThinkingStepByFunctionName(
        'web_search_tool',
        'Search complete: found 5 results',
        true
      )

      const step = useChatStore.getState().thinkingSteps[0]
      expect(step.content).toBe('Search complete: found 5 results')
      expect(step.isComplete).toBe(true)
    })

    test('findThinkingStepByFunctionName finds existing step', () => {
      setupUserMessageContext()

      useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'intent_classifier',
        displayName: 'Intent Classifier',
        content: 'Classifying...',
        isComplete: false,
      })

      const found = useChatStore.getState().findThinkingStepByFunctionName('intent_classifier')

      expect(found).toBeDefined()
      expect(found?.functionName).toBe('intent_classifier')
    })

    test('findThinkingStepByFunctionName returns undefined for non-existent step', () => {
      const found = useChatStore.getState().findThinkingStepByFunctionName('non_existent')

      expect(found).toBeUndefined()
    })

    test('getThinkingStepsForMessage filters by userMessageId', () => {
      useChatStore.getState().setCurrentUser('test-user')

      // Add first user message and its thinking step
      const message1 = useChatStore.getState().addUserMessage('Message 1')
      useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'agent1',
        displayName: 'Agent 1',
        content: 'Step for message 1',
        isComplete: false,
      })

      // Add second user message and its thinking step
      const message2 = useChatStore.getState().addUserMessage('Message 2')
      useChatStore.getState().addThinkingStep({
        category: 'tools',
        functionName: 'tool1',
        displayName: 'Tool 1',
        content: 'Step for message 2',
        isComplete: false,
      })

      // Get steps for each message
      const stepsForMessage1 = useChatStore.getState().getThinkingStepsForMessage(message1.id)
      const stepsForMessage2 = useChatStore.getState().getThinkingStepsForMessage(message2.id)

      expect(stepsForMessage1).toHaveLength(1)
      expect(stepsForMessage1[0].functionName).toBe('agent1')
      expect(stepsForMessage2).toHaveLength(1)
      expect(stepsForMessage2[0].functionName).toBe('tool1')
    })

    test('getThinkingStepsForMessage filters out deep research steps', () => {
      useChatStore.getState().setCurrentUser('test-user')

      // Add user message
      const message = useChatStore.getState().addUserMessage('Test message')

      // Add WebSocket thinking step (should be included)
      useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'websocket_agent',
        displayName: 'WebSocket Agent',
        content: 'WebSocket step',
        isComplete: false,
        isDeepResearch: false,
      })

      // Add deep research thinking step (should be filtered out)
      useChatStore.getState().addThinkingStep({
        category: 'agents',
        functionName: 'deep_research_agent',
        displayName: 'Deep Research Agent',
        content: 'Deep research step',
        isComplete: false,
        isDeepResearch: true,
      })

      // Get steps for the message
      const steps = useChatStore.getState().getThinkingStepsForMessage(message.id)

      // Should only include the WebSocket step, not the deep research step
      expect(steps).toHaveLength(1)
      expect(steps[0].functionName).toBe('websocket_agent')
      expect(steps[0].isDeepResearch).toBe(false)
    })
  })

  describe('report content', () => {
    test('setReportContent sets content', () => {
      useChatStore.getState().setReportContent('# Report\n\nContent here')

      expect(useChatStore.getState().reportContent).toBe('# Report\n\nContent here')
    })

    test('clearReportContent clears content', () => {
      useChatStore.setState({ reportContent: 'Some content' })

      useChatStore.getState().clearReportContent()

      expect(useChatStore.getState().reportContent).toBe('')
    })
  })

  describe('status and prompts', () => {
    const setupConversation = () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })
      return conv
    }

    test('setCurrentStatus sets status', () => {
      useChatStore.getState().setCurrentStatus('searching')

      expect(useChatStore.getState().currentStatus).toBe('searching')
    })

    test('addStatusCard adds status message', () => {
      setupConversation()

      useChatStore.getState().addStatusCard('searching', 'Searching documents...')

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages).toHaveLength(1)
      expect(messages?.[0].messageType).toBe('status')
      expect(messages?.[0].statusType).toBe('searching')
      expect(messages?.[0].content).toBe('Searching documents...')
    })

    test('addAgentPrompt adds prompt message', () => {
      setupConversation()

      useChatStore
        .getState()
        .addAgentPrompt('choice', 'Select an option', ['A', 'B', 'C'], 'Choose one')

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages).toHaveLength(1)
      expect(messages?.[0].messageType).toBe('prompt')
      expect(messages?.[0].promptType).toBe('choice')
      expect(messages?.[0].promptOptions).toEqual(['A', 'B', 'C'])
      expect(messages?.[0].promptPlaceholder).toBe('Choose one')
      expect(messages?.[0].isPromptResponded).toBe(false)
      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    test('respondToPrompt updates prompt message', () => {
      setupConversation()
      useChatStore.getState().addAgentPrompt('choice', 'Pick one', ['A', 'B'])
      const promptId = useChatStore.getState().currentConversation!.messages[0].id!

      useChatStore.getState().respondToPrompt(promptId, 'A')

      const msg = useChatStore.getState().currentConversation?.messages[0]
      expect(msg?.promptResponse).toBe('A')
      expect(msg?.isPromptResponded).toBe(true)
      expect(useChatStore.getState().isLoading).toBe(true)
    })
  })

  describe('agent responses and HITL', () => {
    const setupConversation = () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })
      return conv
    }

    test('addAgentResponse adds response message', () => {
      setupConversation()

      useChatStore.getState().addAgentResponse('Here is your answer', true)

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages).toHaveLength(1)
      expect(messages?.[0].messageType).toBe('agent_response')
      expect(messages?.[0].content).toBe('Here is your answer')
      expect(messages?.[0].showViewReport).toBe(true)
    })

    test('setPendingInteraction sets interaction', () => {
      const interaction: PendingInteraction = {
        id: 'int-1',
        parentId: 'parent-1',
        inputType: 'text',
        text: 'Enter your name',
      }

      useChatStore.getState().setPendingInteraction(interaction)

      expect(useChatStore.getState().pendingInteraction).toEqual(interaction)
    })

    test('clearPendingInteraction clears interaction', () => {
      useChatStore.setState({
        pendingInteraction: { id: 'int-1', parentId: 'p1', inputType: 'text', text: 'Test' },
      })

      useChatStore.getState().clearPendingInteraction()

      expect(useChatStore.getState().pendingInteraction).toBeNull()
    })
  })

  describe('file cards', () => {
    const setupConversation = () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })
      return conv
    }

    test('addFileCard adds file message', () => {
      setupConversation()

      const fileData: FileCardData = {
        fileName: 'document.pdf',
        fileSize: 1024,
        fileStatus: 'uploading',
        progress: 50,
      }

      useChatStore.getState().addFileCard(fileData)

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages).toHaveLength(1)
      expect(messages?.[0].messageType).toBe('file')
      expect(messages?.[0].fileData).toEqual(fileData)
    })

    test('updateFileCard updates file data', () => {
      setupConversation()
      useChatStore.getState().addFileCard({
        fileName: 'doc.pdf',
        fileSize: 1024,
        fileStatus: 'uploading',
        progress: 0,
      })
      const msgId = useChatStore.getState().currentConversation!.messages[0].id!

      useChatStore.getState().updateFileCard(msgId, { fileStatus: 'success', progress: 100 })

      const msg = useChatStore.getState().currentConversation?.messages[0]
      expect(msg?.fileData?.fileStatus).toBe('success')
      expect(msg?.fileData?.progress).toBe(100)
    })
  })

  describe('error cards', () => {
    const setupConversation = () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })
      return conv
    }

    test('addErrorCard adds error message with defaults from registry', () => {
      setupConversation()

      useChatStore.getState().addErrorCard('connection.lost')

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages).toHaveLength(1)
      expect(messages?.[0].messageType).toBe('error')
      expect(messages?.[0].errorData?.errorCode).toBe('connection.lost')
    })

    test('addErrorCard uses custom message', () => {
      setupConversation()

      useChatStore
        .getState()
        .addErrorCard('connection.failed', 'Custom error message', 'Details here')

      const msg = useChatStore.getState().currentConversation?.messages[0]
      expect(msg?.content).toBe('Custom error message')
      expect(msg?.errorData?.errorDetails).toBe('Details here')
    })

    test('dismissErrorCard removes error message', () => {
      setupConversation()
      useChatStore.getState().addErrorCard('system.unknown')
      const msgId = useChatStore.getState().currentConversation!.messages[0].id!

      useChatStore.getState().dismissErrorCard(msgId)

      expect(useChatStore.getState().currentConversation?.messages).toHaveLength(0)
    })
  })

  describe('file upload status cards', () => {
    test('addFileUploadStatusCard adds to current conversation', () => {
      const conv: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv,
        conversations: [conv],
      })

      useChatStore.getState().addFileUploadStatusCard('uploaded', 3, 'job-123')

      const messages = useChatStore.getState().currentConversation?.messages
      expect(messages).toHaveLength(1)
      expect(messages?.[0].messageType).toBe('file_upload_status')
      expect(messages?.[0].fileUploadStatusData?.type).toBe('uploaded')
      expect(messages?.[0].fileUploadStatusData?.fileCount).toBe(3)
      expect(messages?.[0].fileUploadStatusData?.jobId).toBe('job-123')
    })

    test('addFileUploadStatusCard adds to specific session', () => {
      const conv1: Conversation = {
        id: 'conv-1',
        userId: 'user-1',
        title: 'Current',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      const conv2: Conversation = {
        id: 'conv-2',
        userId: 'user-1',
        title: 'Target',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }
      useChatStore.setState({
        currentUserId: 'user-1',
        currentConversation: conv1,
        conversations: [conv1, conv2],
      })

      useChatStore.getState().addFileUploadStatusCard('uploaded', 2, 'job-456', 'conv-2')

      // Current conversation should be unchanged
      expect(useChatStore.getState().currentConversation?.messages).toHaveLength(0)

      // Target conversation should have the message
      const targetConv = useChatStore.getState().conversations.find((c) => c.id === 'conv-2')
      expect(targetConv?.messages).toHaveLength(1)
      expect(targetConv?.messages[0].fileUploadStatusData?.type).toBe('uploaded')
    })
  })

  describe('restoreSessionState — interrupted response detection', () => {
    const createConversation = (messages: Partial<Conversation['messages'][0]>[]): Conversation => ({
      id: 'conv-restore',
      userId: 'user-1',
      title: 'Restore Test',
      messages: messages.map((m, i) => ({
        id: `msg-${i}`,
        role: (m.role ?? 'user') as 'user' | 'assistant' | 'system',
        content: m.content ?? '',
        timestamp: new Date(),
        ...m,
      })),
      createdAt: new Date(),
      updatedAt: new Date(),
    })

    test('adds error card when last meaningful message is user with thinking steps', () => {
      const conv = createConversation([
        {
          role: 'user',
          messageType: 'user',
          content: 'Tell me about AI',
          thinkingSteps: [
            { id: 's1', userMessageId: 'msg-0', category: 'tasks', functionName: 'fn', displayName: 'Searching', content: '', isComplete: true, timestamp: new Date() },
          ],
        },
      ])

      // Set currentConversation before calling restoreSessionState
      useChatStore.setState({ currentConversation: conv, conversations: [conv] })
      useChatStore.getState().restoreSessionState(conv)

      // Should have added an error card
      const messages = useChatStore.getState().currentConversation?.messages ?? []
      expect(messages).toHaveLength(2)
      expect(messages[1].messageType).toBe('error')
      expect(messages[1].errorData?.errorCode).toBe('agent.response_interrupted')
    })

    test('does NOT add error card when last message is an assistant response', () => {
      const conv = createConversation([
        { role: 'user', messageType: 'user', content: 'Hello',
          thinkingSteps: [{ id: 's1', userMessageId: 'msg-0', category: 'tasks', functionName: 'fn', displayName: 'Thinking', content: '', isComplete: true, timestamp: new Date() }],
        },
        { role: 'assistant', messageType: 'agent_response', content: 'Hi there!' },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })
      useChatStore.getState().restoreSessionState(conv)

      // No error card added — response was completed
      const messages = useChatStore.getState().currentConversation?.messages ?? []
      expect(messages).toHaveLength(2)
      expect(messages.every((m) => m.messageType !== 'error')).toBe(true)
    })

    test('does NOT add error card when user message has no thinking steps', () => {
      const conv = createConversation([
        { role: 'user', messageType: 'user', content: 'Hello' },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })
      useChatStore.getState().restoreSessionState(conv)

      // No error card — no thinking steps means processing never started
      const messages = useChatStore.getState().currentConversation?.messages ?? []
      expect(messages).toHaveLength(1)
    })

    test('does NOT add error card when pending HITL interaction exists', () => {
      const conv = createConversation([
        {
          role: 'user',
          messageType: 'user',
          content: 'Research AI',
          thinkingSteps: [{ id: 's1', userMessageId: 'msg-0', category: 'tasks', functionName: 'fn', displayName: 'Planning', content: '', isComplete: true, timestamp: new Date() }],
        },
        {
          role: 'assistant',
          messageType: 'prompt',
          content: 'Approve this plan?',
          promptId: 'p-1',
          promptParentId: 'msg-0',
          promptInputType: 'approval',
          isPromptResponded: false,
        },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })
      useChatStore.getState().restoreSessionState(conv)

      // No error card — unresponded prompt restores pendingInteraction, not an interruption
      const messages = useChatStore.getState().currentConversation?.messages ?? []
      expect(messages.every((m) => m.errorData?.errorCode !== 'agent.response_interrupted')).toBe(true)
    })

    test('does NOT double-add error card on repeated restore calls', () => {
      const conv = createConversation([
        {
          role: 'user',
          messageType: 'user',
          content: 'Tell me about AI',
          thinkingSteps: [{ id: 's1', userMessageId: 'msg-0', category: 'tasks', functionName: 'fn', displayName: 'Searching', content: '', isComplete: true, timestamp: new Date() }],
        },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })

      // First restore — adds error card
      useChatStore.getState().restoreSessionState(conv)
      const afterFirst = useChatStore.getState().currentConversation?.messages ?? []
      expect(afterFirst.filter((m) => m.errorData?.errorCode === 'agent.response_interrupted')).toHaveLength(1)

      // Second restore with updated conversation (now includes error card)
      const updatedConv = useChatStore.getState().currentConversation!
      useChatStore.getState().restoreSessionState(updatedConv)
      const afterSecond = useChatStore.getState().currentConversation?.messages ?? []
      expect(afterSecond.filter((m) => m.errorData?.errorCode === 'agent.response_interrupted')).toHaveLength(1)
    })
  })

  describe('cleanupOrphanedStartingBanners', () => {
    const createConversation = (messages: Partial<Conversation['messages'][0]>[]): Conversation => ({
      id: 'conv-orphaned',
      userId: 'user-1',
      title: 'Orphaned Banner Test',
      messages: messages.map((m, i) => ({
        id: m.id ?? `msg-${i}`,
        role: (m.role ?? 'assistant') as 'user' | 'assistant' | 'system',
        content: m.content ?? '',
        timestamp: new Date(),
        ...m,
      })),
      createdAt: new Date(),
      updatedAt: new Date(),
    })

    test('syncs stale tracking message when terminal banner already exists', async () => {
      const conv = createConversation([
        {
          id: 'tracking-msg',
          messageType: 'agent_response',
          deepResearchJobId: 'job-123',
          deepResearchJobStatus: 'running',
          isDeepResearchActive: true,
        },
        {
          id: 'starting-banner',
          messageType: 'deep_research_banner',
          deepResearchBannerData: { bannerType: 'starting', jobId: 'job-123' },
        },
        {
          id: 'failure-banner',
          messageType: 'deep_research_banner',
          deepResearchBannerData: { bannerType: 'failure', jobId: 'job-123' },
        },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })

      await useChatStore.getState().cleanupOrphanedStartingBanners()

      const updatedMessages = useChatStore.getState().currentConversation?.messages ?? []
      const trackingMessage = updatedMessages.find((m) => m.id === 'tracking-msg')

      expect(updatedMessages.some((m) => m.id === 'starting-banner')).toBe(false)
      expect(trackingMessage?.deepResearchJobStatus).toBe('failure')
      expect(trackingMessage?.isDeepResearchActive).toBe(false)
    })

    test('syncs stale tracking message after REST status resolves terminal state', async () => {
      mockDeepResearchApi.getJobStatus.mockResolvedValue({
        job_id: 'job-456',
        status: 'failure',
        error: 'expired',
      })

      const conv = createConversation([
        {
          id: 'tracking-msg',
          messageType: 'agent_response',
          deepResearchJobId: 'job-456',
          deepResearchJobStatus: 'running',
          isDeepResearchActive: true,
        },
        {
          id: 'starting-banner',
          messageType: 'deep_research_banner',
          deepResearchBannerData: { bannerType: 'starting', jobId: 'job-456' },
        },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })

      await useChatStore.getState().cleanupOrphanedStartingBanners()

      const updatedMessages = useChatStore.getState().currentConversation?.messages ?? []
      const trackingMessage = updatedMessages.find((m) => m.id === 'tracking-msg')
      const terminalBanner = updatedMessages.find(
        (m) =>
          m.messageType === 'deep_research_banner' &&
          m.deepResearchBannerData?.jobId === 'job-456' &&
          m.deepResearchBannerData?.bannerType === 'failure'
      )

      expect(trackingMessage?.deepResearchJobStatus).toBe('failure')
      expect(trackingMessage?.isDeepResearchActive).toBe(false)
      expect(updatedMessages.some((m) => m.id === 'starting-banner')).toBe(false)
      expect(terminalBanner).toBeTruthy()
    })
  })

  describe('reconnectToActiveJob', () => {
    const createConversation = (messages: Partial<Conversation['messages'][0]>[]): Conversation => ({
      id: 'conv-reconnect',
      userId: 'user-1',
      title: 'Reconnect Test',
      messages: messages.map((m, i) => ({
        id: m.id ?? `msg-${i}`,
        role: (m.role ?? 'assistant') as 'user' | 'assistant' | 'system',
        content: m.content ?? '',
        timestamp: new Date(),
        ...m,
      })),
      createdAt: new Date(),
      updatedAt: new Date(),
    })

    test('marks missing active job as failed when status lookup returns 404', async () => {
      mockDeepResearchApi.getJobStatus.mockRejectedValue(new Error('Failed to get job status: 404'))

      const conv = createConversation([
        {
          id: 'tracking-msg',
          messageType: 'agent_response',
          deepResearchJobId: 'job-missing',
          deepResearchJobStatus: 'running',
          isDeepResearchActive: true,
        },
        {
          id: 'starting-banner',
          messageType: 'deep_research_banner',
          deepResearchBannerData: { bannerType: 'starting', jobId: 'job-missing' },
        },
      ])

      useChatStore.setState({ currentConversation: conv, conversations: [conv] })

      await useChatStore.getState().reconnectToActiveJob()

      const updatedMessages = useChatStore.getState().currentConversation?.messages ?? []
      const trackingMessage = updatedMessages.find((m) => m.id === 'tracking-msg')
      const failureBanner = updatedMessages.find(
        (m) =>
          m.messageType === 'deep_research_banner' &&
          m.deepResearchBannerData?.jobId === 'job-missing' &&
          m.deepResearchBannerData?.bannerType === 'failure'
      )

      expect(trackingMessage?.deepResearchJobStatus).toBe('failure')
      expect(trackingMessage?.isDeepResearchActive).toBe(false)
      expect(updatedMessages.some((m) => m.id === 'starting-banner')).toBe(false)
      expect(failureBanner).toBeTruthy()
    })
  })
})
