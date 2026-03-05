// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { useChat } from './use-chat'

// Mock store actions
const mockAddUserMessage = vi.fn()
const mockAddAgentResponse = vi.fn()
const mockAddThinkingStep = vi.fn(() => 'step-1')
const mockAppendToThinkingStep = vi.fn()
const mockCompleteThinkingStep = vi.fn()
const mockSetReportContent = vi.fn()
const mockAddStatusCard = vi.fn()
const mockAddAgentPrompt = vi.fn()
const mockAddErrorCard = vi.fn()
const mockSetCurrentStatus = vi.fn()
const mockSetLoading = vi.fn()
const mockSetStreaming = vi.fn()
const mockClearThinkingSteps = vi.fn()
const mockClearReportContent = vi.fn()
const mockCreateConversation = vi.fn()
const mockSetCurrentUser = vi.fn()
const mockGetUserConversations = vi.fn((): unknown[] => [])
const mockSelectConversation = vi.fn()

// Mock store state
let mockStoreState = {
  currentUserId: 'user-1',
  currentConversation: { id: 'conv-1', messages: [], userId: 'user-1' },
  conversations: [],
  isStreaming: false,
  isLoading: false,
  thinkingSteps: [],
  activeThinkingStepId: null,
  reportContent: '',
  currentStatus: null,
  pendingInteraction: null,
}

vi.mock('../store', () => ({
  useChatStore: Object.assign(
    vi.fn(() => ({
      ...mockStoreState,
      addUserMessage: mockAddUserMessage,
      addAgentResponse: mockAddAgentResponse,
      addThinkingStep: mockAddThinkingStep,
      appendToThinkingStep: mockAppendToThinkingStep,
      completeThinkingStep: mockCompleteThinkingStep,
      setReportContent: mockSetReportContent,
      addStatusCard: mockAddStatusCard,
      addAgentPrompt: mockAddAgentPrompt,
      addErrorCard: mockAddErrorCard,
      setCurrentStatus: mockSetCurrentStatus,
      setLoading: mockSetLoading,
      setStreaming: mockSetStreaming,
      clearThinkingSteps: mockClearThinkingSteps,
      clearReportContent: mockClearReportContent,
      createConversation: mockCreateConversation,
      setCurrentUser: mockSetCurrentUser,
      getUserConversations: mockGetUserConversations,
      selectConversation: mockSelectConversation,
    })),
    {
      getState: vi.fn(() => mockStoreState),
    }
  ),
}))

// Mock auth hook
vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({
    user: { id: 'user-1', email: 'test@example.com' },
    idToken: 'mock-id-token',
  })),
}))

// Mock the streamGenerate API
const mockStreamGenerate = vi.fn()
vi.mock('@/adapters/api/chat-client', () => ({
  streamGenerate: (...args: unknown[]) => mockStreamGenerate(...args),
}))

import { useChatStore } from '../store'

describe('useChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStoreState = {
      currentUserId: 'user-1',
      currentConversation: { id: 'conv-1', messages: [], userId: 'user-1' },
      conversations: [],
      isStreaming: false,
      isLoading: false,
      thinkingSteps: [],
      activeThinkingStepId: null,
      reportContent: '',
      currentStatus: null,
      pendingInteraction: null,
    }
    vi.mocked(useChatStore).getState = vi.fn(
      () => mockStoreState
    ) as unknown as typeof useChatStore.getState
  })

  test('returns initial state from store', () => {
    const { result } = renderHook(() => useChat())

    expect(result.current.isStreaming).toBe(false)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.messages).toEqual([])
    expect(result.current.conversation).toEqual(mockStoreState.currentConversation)
    expect(result.current.thinkingSteps).toEqual([])
    expect(result.current.reportContent).toBe('')
    expect(result.current.currentStatus).toBeNull()
    expect(result.current.pendingInteraction).toBeNull()
  })

  test('syncs user ID to store on mount', () => {
    renderHook(() => useChat())

    expect(mockSetCurrentUser).toHaveBeenCalledWith('user-1')
  })

  test('sendMessage does nothing for empty content', async () => {
    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('')
    })

    expect(mockAddUserMessage).not.toHaveBeenCalled()
    expect(mockStreamGenerate).not.toHaveBeenCalled()
  })

  test('sendMessage does nothing for whitespace-only content', async () => {
    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('   ')
    })

    expect(mockAddUserMessage).not.toHaveBeenCalled()
  })

  test('sendMessage adds user message and starts streaming', async () => {
    mockStreamGenerate.mockResolvedValue(undefined)

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockAddUserMessage).toHaveBeenCalledWith('Hello')
    expect(mockClearThinkingSteps).toHaveBeenCalled()
    expect(mockClearReportContent).toHaveBeenCalled()
    expect(mockSetCurrentStatus).toHaveBeenCalledWith('thinking')
    expect(mockAddThinkingStep).toHaveBeenCalledWith({
      category: 'tasks',
      functionName: '<workflow>',
      displayName: 'Workflow',
      content: 'Starting...',
      isComplete: false,
    })
    expect(mockSetStreaming).toHaveBeenCalledWith(true)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('sendMessage calls streamGenerate with correct options', async () => {
    mockStreamGenerate.mockResolvedValue(undefined)

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Test message')
    })

    expect(mockStreamGenerate).toHaveBeenCalledWith(
      expect.objectContaining({
        inputMessage: 'Test message',
        sessionId: 'conv-1',
        authToken: 'mock-id-token',
      }),
      expect.any(Object)
    )
  })

  test('sendMessage routes onThinking callback to store', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      callbacks.onThinking('Thinking content...')
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockAppendToThinkingStep).toHaveBeenCalledWith('step-1', 'Thinking content...')
  })

  test('sendMessage routes onStatus callback to store', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      callbacks.onStatus('searching', 'Searching documents...')
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockCompleteThinkingStep).toHaveBeenCalledWith('step-1')
    expect(mockAddThinkingStep).toHaveBeenCalledWith(
      expect.objectContaining({
        category: 'tasks',
        functionName: '<searching>',
        displayName: 'Searching',
        isComplete: false,
      })
    )
    expect(mockSetCurrentStatus).toHaveBeenCalledWith('searching')
    expect(mockAddStatusCard).toHaveBeenCalledWith('searching', 'Searching documents...')
  })

  test('sendMessage routes onPrompt callback to store', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      callbacks.onPrompt(
        'clarification',
        'What do you mean?',
        ['Option A', 'Option B'],
        'Choose one'
      )
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockAddAgentPrompt).toHaveBeenCalledWith(
      'clarification',
      'What do you mean?',
      ['Option A', 'Option B'],
      'Choose one'
    )
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
  })

  test('sendMessage routes onReport callback to store', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      callbacks.onReport('Final report content')
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockSetReportContent).toHaveBeenCalledWith('Final report content')
  })

  test('sendMessage handles onComplete callback', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      callbacks.onComplete?.()
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockCompleteThinkingStep).toHaveBeenCalledWith('step-1')
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetCurrentStatus).toHaveBeenCalledWith('complete')
    expect(mockAddStatusCard).toHaveBeenCalledWith('complete', 'Research complete')
  })

  test('sendMessage handles onError callback', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      callbacks.onError?.(new Error('API error'))
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockCompleteThinkingStep).toHaveBeenCalledWith('step-1')
    expect(mockAddErrorCard).toHaveBeenCalledWith('agent.response_failed', 'API error')
    expect(mockSetCurrentStatus).toHaveBeenCalledWith(null)
  })

  test('sendMessage handles thrown errors', async () => {
    mockStreamGenerate.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockCompleteThinkingStep).toHaveBeenCalled()
    expect(mockAddErrorCard).toHaveBeenCalledWith('agent.response_failed', 'Network error')
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
  })

  test('sendMessage ignores AbortError', async () => {
    const abortError = new Error('Aborted')
    abortError.name = 'AbortError'
    mockStreamGenerate.mockRejectedValue(abortError)

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockAddErrorCard).not.toHaveBeenCalled()
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
  })

  test('sendMessage throws when no conversation exists', async () => {
    vi.mocked(useChatStore).getState = vi.fn(() => ({
      ...mockStoreState,
      currentConversation: null,
    })) as unknown as typeof useChatStore.getState

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    expect(mockAddErrorCard).toHaveBeenCalledWith('agent.response_failed', 'No active conversation')
  })

  test('createConversation calls store action', () => {
    const { result } = renderHook(() => useChat())

    act(() => {
      result.current.createConversation()
    })

    expect(mockCreateConversation).toHaveBeenCalled()
  })

  test('selectConversation calls store action with ID', () => {
    const { result } = renderHook(() => useChat())

    act(() => {
      result.current.selectConversation('conv-2')
    })

    expect(mockSelectConversation).toHaveBeenCalledWith('conv-2')
  })

  test('respondToInteraction logs warning (SSE mode does not support HITL)', () => {
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const { result } = renderHook(() => useChat())

    act(() => {
      result.current.respondToInteraction('response')
    })

    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining('respondToInteraction called in SSE mode')
    )

    consoleWarnSpy.mockRestore()
  })

  test('getUserConversations returns filtered conversations', () => {
    const mockConversations = [
      { id: 'conv-1', userId: 'user-1', title: 'Conv 1' },
      { id: 'conv-2', userId: 'user-1', title: 'Conv 2' },
    ]
    mockGetUserConversations.mockReturnValue(mockConversations)

    const { result } = renderHook(() => useChat())

    expect(result.current.userConversations).toEqual(mockConversations)
  })

  test('status change creates new thinking step', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      // Status changes from 'thinking' (set before streamGenerate) to 'searching'
      callbacks.onStatus('searching', 'Searching...')
    })

    // Track addThinkingStep calls to return different IDs
    let stepCounter = 0
    mockAddThinkingStep.mockImplementation(() => `step-${++stepCounter}`)

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    // Should complete previous step and create new one
    expect(mockCompleteThinkingStep).toHaveBeenCalledWith('step-1')
    // Initial 'thinking' step + 'searching' step = 2 calls
    expect(mockAddThinkingStep).toHaveBeenCalledTimes(2)
    expect(mockAddThinkingStep).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ functionName: '<workflow>' })
    )
    expect(mockAddThinkingStep).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ functionName: '<searching>' })
    )
  })

  test('same status does not create new thinking step', async () => {
    mockStreamGenerate.mockImplementation(async (_options, callbacks) => {
      // Same status as initial ('thinking') - should NOT create new step
      callbacks.onStatus('thinking', 'Still thinking...')
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.sendMessage('Hello')
    })

    // Should only create initial thinking step (status 'thinking' is same as initial)
    expect(mockAddThinkingStep).toHaveBeenCalledTimes(1)
    expect(mockAddThinkingStep).toHaveBeenCalledWith(
      expect.objectContaining({ functionName: '<workflow>' })
    )
    // Should NOT complete the step since status didn't change
    expect(mockCompleteThinkingStep).not.toHaveBeenCalled()
  })
})
