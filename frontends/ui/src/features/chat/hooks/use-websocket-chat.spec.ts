// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act, waitFor } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach, afterEach } from 'vitest'
import { useWebSocketChat } from './use-websocket-chat'
import { useAuth } from '@/adapters/auth'
import { createNATWebSocketClient } from '@/adapters/api/websocket-client'

// Mock store actions
const mockAddUserMessage = vi.fn()
const mockAddAgentResponse = vi.fn()
const mockAddAgentResponseWithMeta = vi.fn(() => 'msg-1')
const mockAddThinkingStep = vi.fn(() => 'step-1')
const mockAppendToThinkingStep = vi.fn()
const mockCompleteThinkingStep = vi.fn()
const mockUpdateThinkingStepByFunctionName = vi.fn()
const mockFindThinkingStepByFunctionName = vi.fn(() => undefined)
const mockSetReportContent = vi.fn()
const mockAddStatusCard = vi.fn()
const mockAddAgentPrompt = vi.fn()
const mockAddErrorCard = vi.fn()
const mockSetCurrentStatus = vi.fn()
const mockSetPendingInteraction = vi.fn()
const mockClearPendingInteraction = vi.fn()
const mockSetLoading = vi.fn()
const mockSetStreaming = vi.fn()
const mockClearThinkingSteps = vi.fn()
const mockClearReportContent = vi.fn()
const mockCreateConversation = vi.fn()
const mockSetCurrentUser = vi.fn()
const mockGetUserConversations = vi.fn(() => [])
const mockSelectConversation = vi.fn()
const mockRespondToPrompt = vi.fn()
const mockAddPlanMessage = vi.fn()
const mockUpdatePlanMessageResponse = vi.fn()
const mockAddDeepResearchBanner = vi.fn()
const mockDismissConnectionErrors = vi.fn()

// Mock store state
let mockStoreState: {
  currentUserId: string | null
  currentConversation: { id: string; messages: unknown[]; userId: string } | null
  conversations: unknown[]
  isStreaming: boolean
  isLoading: boolean
  error: string | null
  thinkingSteps: unknown[]
  activeThinkingStepId: string | null
  reportContent: string
  currentStatus: string | null
  pendingInteraction: { id: string; parentId: string; inputType: string; text: string } | null
  planMessages: unknown[]
} = {
  currentUserId: 'user-1',
  currentConversation: { id: 'conv-1', messages: [], userId: 'user-1' },
  conversations: [],
  isStreaming: false,
  isLoading: false,
  error: null,
  thinkingSteps: [],
  activeThinkingStepId: null,
  reportContent: '',
  currentStatus: null,
  pendingInteraction: null,
  planMessages: [],
}

/**
 * Build the default selector-based useChatStore mock body.
 *
 * Extracted as a helper so suites that override useChatStore with their own
 * mockImplementation (e.g. the deep-research escalation test) can restore
 * the default in afterEach without duplicating the action wiring.
 */
const defaultUseChatStoreImpl = (selector?: (s: any) => any) => {
  const state = {
    ...mockStoreState,
    addUserMessage: mockAddUserMessage,
    addAgentResponse: mockAddAgentResponse,
    addAgentResponseWithMeta: mockAddAgentResponseWithMeta,
    addThinkingStep: mockAddThinkingStep,
    appendToThinkingStep: mockAppendToThinkingStep,
    completeThinkingStep: mockCompleteThinkingStep,
    updateThinkingStepByFunctionName: mockUpdateThinkingStepByFunctionName,
    findThinkingStepByFunctionName: mockFindThinkingStepByFunctionName,
    setReportContent: mockSetReportContent,
    addStatusCard: mockAddStatusCard,
    addAgentPrompt: mockAddAgentPrompt,
    addErrorCard: mockAddErrorCard,
    setCurrentStatus: mockSetCurrentStatus,
    setPendingInteraction: mockSetPendingInteraction,
    clearPendingInteraction: mockClearPendingInteraction,
    setLoading: mockSetLoading,
    setStreaming: mockSetStreaming,
    clearThinkingSteps: mockClearThinkingSteps,
    clearReportContent: mockClearReportContent,
    createConversation: mockCreateConversation,
    setCurrentUser: mockSetCurrentUser,
    getUserConversations: mockGetUserConversations,
    selectConversation: mockSelectConversation,
    respondToPrompt: mockRespondToPrompt,
    addPlanMessage: mockAddPlanMessage,
    updatePlanMessageResponse: mockUpdatePlanMessageResponse,
    addDeepResearchBanner: mockAddDeepResearchBanner,
    dismissConnectionErrors: mockDismissConnectionErrors,
  }
  return selector ? selector(state) : state
}

vi.mock('../store', () => ({
  useChatStore: Object.assign(
    // Wrap in lambda so the reference to `defaultUseChatStoreImpl` is
    // resolved at call time (not at vi.mock hoist time). Without the
    // lambda, vi.fn would read the const eagerly and hit TDZ.
    vi.fn((selector?: (s: any) => any) => defaultUseChatStoreImpl(selector)),
    {
      getState: vi.fn(() => ({
        ...mockStoreState,
      })),
    }
  ),
  selectHasConnectionError: () => false,
}))

// Mock auth hook (per-test override via vi.mocked(useAuth).mockReturnValue(...))
vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({
    user: { id: 'user-1', email: 'test@example.com' },
    idToken: 'mock-id-token',
    authRequired: false,
    error: undefined,
  })),
}))

// Mock next-auth/react getSession so the token-rotation logic in
// useWebSocketChat doesn't try to talk to a real /api/auth/session endpoint.
const mockGetSession = vi.fn<() => Promise<{ idTokenExpiresAt?: number } | null>>()
vi.mock('next-auth/react', () => ({
  getSession: () => mockGetSession(),
}))

// Mock connection recovery hook (tested separately)
vi.mock('./use-connection-recovery', () => ({
  useConnectionRecovery: vi.fn(),
}))

// Mock backend health check
const mockCheckBackendHealthCached = vi.fn<() => Promise<boolean>>().mockResolvedValue(false)
vi.mock('@/shared/hooks/use-backend-health', () => ({
  checkBackendHealthCached: () => mockCheckBackendHealthCached(),
  invalidateHealthCache: vi.fn(),
}))

// Mock layout store
vi.mock('@/features/layout/store', () => ({
  useLayoutStore: Object.assign(
    vi.fn((selector?: (s: any) => any) => {
      const state = {
        enabledDataSourceIds: ['source-1', 'source-2'],
        knowledgeLayerAvailable: false,
      }
      return selector ? selector(state) : state
    }),
    {
      getState: vi.fn(() => ({
        enabledDataSourceIds: ['source-1', 'source-2'],
      })),
    }
  ),
}))

// Mock documents store
vi.mock('@/features/documents/store', () => ({
  useDocumentsStore: Object.assign(
    vi.fn((selector?: (s: any) => any) => {
      const state = {
        trackedFiles: [],
      }
      return selector ? selector(state) : state
    }),
    {
      getState: vi.fn(() => ({
        trackedFiles: [],
      })),
    }
  ),
}))

// Mock WebSocket client
const mockWsClient = {
  connect: vi.fn(),
  disconnect: vi.fn(),
  rotate: vi.fn(),
  sendMessage: vi.fn(() => 'mock-outbound-message-id'),
  sendInteractionResponse: vi.fn(() => 'mock-outbound-interaction-id'),
  isConnected: vi.fn(() => false),
  updateConversationId: vi.fn(),
}

let capturedCallbacks: {
  onResponse?: (content: string, status: string, isFinal: boolean, parentId?: string) => void
  onIntermediateStep?: (content: unknown, status: string, parentId?: string) => void
  onHumanPrompt?: (promptId: string, parentId: string, prompt: unknown) => void
  onError?: (error: { code: string; message: string; details?: string }) => void
  onConnectionChange?: (status: string, context?: { intentional?: boolean }) => void
} = {}

// Captured separately so token-rotation tests can drive it directly without
// depending on React state propagation timing.
let capturedOnBeforeReconnect: (() => Promise<void>) | undefined

vi.mock('@/adapters/api/websocket-client', () => ({
  createNATWebSocketClient: vi.fn((options: {
    callbacks: typeof capturedCallbacks
    onBeforeReconnect?: () => Promise<void>
  }) => {
    capturedCallbacks = options.callbacks
    capturedOnBeforeReconnect = options.onBeforeReconnect
    return mockWsClient
  }),
  NATWebSocketClient: vi.fn(),
  HumanPromptType: {
    TEXT: 'text',
    MULTIPLE_CHOICE: 'multiple_choice',
    BINARY_CHOICE: 'binary_choice',
    APPROVAL: 'approval',
  },
}))

import { useChatStore } from '../store'

/**
 * Helper to render hook with autoConnect enabled (default behavior)
 * This triggers the useEffect that creates the WebSocket client
 */
function renderWebSocketHook(options: { autoConnect?: boolean } = {}) {
  return renderHook(() => useWebSocketChat(options))
}

describe('useWebSocketChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedCallbacks = {}
    capturedOnBeforeReconnect = undefined
    mockGetSession.mockReset()
    // Restore default useChatStore mock so a previous test's
    // mockImplementation override (e.g. deep-research escalation) doesn't
    // leak into this one.
    vi.mocked(useChatStore).mockImplementation(defaultUseChatStoreImpl)
    mockStoreState = {
      currentUserId: 'user-1',
      currentConversation: { id: 'conv-1', messages: [], userId: 'user-1' },
      conversations: [],
      isStreaming: false,
      isLoading: false,
      error: null,
      thinkingSteps: [],
      activeThinkingStepId: null,
      reportContent: '',
      currentStatus: null,
      pendingInteraction: null,
      planMessages: [],
    }
    vi.mocked(useChatStore).getState = vi.fn(() => mockStoreState) as unknown as typeof useChatStore.getState
    mockWsClient.isConnected.mockReturnValue(false)
  })

  test('returns initial state from store', () => {
    const { result } = renderWebSocketHook({ autoConnect: false })

    expect(result.current.isStreaming).toBe(false)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.messages).toEqual([])
    expect(result.current.conversation).toEqual(mockStoreState.currentConversation)
    expect(result.current.thinkingSteps).toEqual([])
    expect(result.current.reportContent).toBe('')
    expect(result.current.currentStatus).toBeNull()
    expect(result.current.pendingInteraction).toBeNull()
    expect(result.current.isConnected).toBe(false)
  })

  test('syncs user ID to store on mount', () => {
    renderWebSocketHook({ autoConnect: false })

    expect(mockSetCurrentUser).toHaveBeenCalledWith('user-1')
  })

  test('sendMessage does nothing for empty content', () => {
    const { result } = renderWebSocketHook({ autoConnect: false })

    act(() => {
      result.current.sendMessage('')
    })

    expect(mockAddUserMessage).not.toHaveBeenCalled()
  })

  test('sendMessage does nothing for whitespace-only content', () => {
    const { result } = renderWebSocketHook({ autoConnect: false })

    act(() => {
      result.current.sendMessage('   ')
    })

    expect(mockAddUserMessage).not.toHaveBeenCalled()
  })

  test('sendMessage adds user message and prepares for streaming', () => {
    mockWsClient.isConnected.mockReturnValue(true)

    // autoConnect: true triggers useEffect that creates the WebSocket client
    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Hello')
    })

    expect(mockAddUserMessage).toHaveBeenCalledWith('Hello', {
      enabledDataSources: ['source-1', 'source-2'],
      messageFiles: [],
    })
    // Note: clearThinkingSteps is no longer called - thinking steps persist per userMessageId for chat history
    expect(mockClearReportContent).toHaveBeenCalled()
    expect(mockClearPendingInteraction).toHaveBeenCalled()
    expect(mockSetCurrentStatus).toHaveBeenCalledWith('thinking')
    expect(mockAddThinkingStep).not.toHaveBeenCalled()
    expect(mockSetStreaming).toHaveBeenCalledWith(true)
    expect(mockSetLoading).toHaveBeenCalledWith(true)
  })

  test('sendMessage sends via WebSocket when connected', () => {
    mockWsClient.isConnected.mockReturnValue(true)

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Hello')
    })

    // sendMessage is called with content and enabled data sources
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Hello', expect.any(Array))
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('sendMessage while the existing socket is connecting buffers instead of creating a parallel client', () => {
    mockWsClient.isConnected.mockReturnValue(false)
    const { result } = renderWebSocketHook()
    vi.mocked(createNATWebSocketClient).mockClear()
    mockWsClient.connect.mockClear()
    mockWsClient.sendMessage.mockClear()

    act(() => {
      result.current.sendMessage('Send during handshake')
    })

    expect(createNATWebSocketClient).not.toHaveBeenCalled()
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    expect(mockWsClient.connect).toHaveBeenCalledTimes(1)

    mockWsClient.isConnected.mockReturnValue(true)
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledWith(
      'Send during handshake',
      expect.any(Array),
    )
  })

  test('replays a just-sent message once when the socket drops before any backend frame', () => {
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendMessage
      .mockReturnValueOnce('outbound-original')
      .mockReturnValueOnce('outbound-replay')

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Need current weather')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledWith(
      'Need current weather',
      expect.any(Array),
    )

    mockWsClient.sendMessage.mockClear()
    mockSetStreaming.mockClear()
    mockSetLoading.mockClear()
    mockAddErrorCard.mockClear()

    act(() => {
      capturedCallbacks.onConnectionChange?.('disconnected')
    })

    expect(mockSetStreaming).not.toHaveBeenCalledWith(false)
    expect(mockSetLoading).not.toHaveBeenCalledWith(false)
    expect(mockAddErrorCard).not.toHaveBeenCalled()

    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledTimes(1)
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith(
      'Need current weather',
      expect.any(Array),
    )

    // Once any backend frame arrives, the delivery guard is cleared. A later
    // disconnect must not replay the same prompt again.
    mockStoreState.isStreaming = true
    mockWsClient.sendMessage.mockClear()

    act(() => {
      capturedCallbacks.onIntermediateStep?.('Thinking...', 'in_progress')
    })
    act(() => {
      capturedCallbacks.onConnectionChange?.('disconnected')
    })
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  test('does not replay an unacknowledged message more than once', () => {
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendMessage
      .mockReturnValueOnce('outbound-original')
      .mockReturnValueOnce('outbound-replay')

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Retry bounded request')
    })

    mockWsClient.sendMessage.mockClear()

    act(() => {
      capturedCallbacks.onConnectionChange?.('disconnected')
    })
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledTimes(1)

    mockWsClient.sendMessage.mockClear()
    mockSetStreaming.mockClear()
    mockSetLoading.mockClear()

    act(() => {
      capturedCallbacks.onConnectionChange?.('disconnected')
    })
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('replays a just-sent message once when no backend frame arrives before the ack timeout', () => {
    vi.useFakeTimers()
    try {
      mockWsClient.isConnected.mockReturnValue(true)
      mockWsClient.sendMessage
        .mockReturnValueOnce('outbound-original')
        .mockReturnValueOnce('outbound-replay')

      const { result } = renderWebSocketHook()

      act(() => {
        result.current.sendMessage('Request after stale socket')
      })

      mockWsClient.sendMessage.mockClear()
      mockWsClient.rotate.mockClear()
      mockSetStreaming.mockClear()
      mockSetLoading.mockClear()
      mockAddErrorCard.mockClear()

      act(() => {
        vi.advanceTimersByTime(7_000)
      })

      expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
      expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
      expect(mockSetStreaming).not.toHaveBeenCalledWith(false)
      expect(mockSetLoading).not.toHaveBeenCalledWith(false)
      expect(mockAddErrorCard).not.toHaveBeenCalled()

      act(() => {
        capturedCallbacks.onConnectionChange?.('connected')
      })

      expect(mockWsClient.sendMessage).toHaveBeenCalledTimes(1)
      expect(mockWsClient.sendMessage).toHaveBeenCalledWith(
        'Request after stale socket',
        expect.any(Array),
      )
    } finally {
      vi.useRealTimers()
    }
  })

  test('does not replay after an accepted intermediate frame with an internal parent id before the ack timeout', () => {
    vi.useFakeTimers()
    try {
      mockWsClient.isConnected.mockReturnValue(true)
      mockWsClient.sendMessage.mockReturnValueOnce('outbound-original')

      const { result } = renderWebSocketHook()

      act(() => {
        result.current.sendMessage('Request that gets a response')
      })

      mockStoreState.isStreaming = true
      act(() => {
        capturedCallbacks.onIntermediateStep?.('Thinking...', 'in_progress', 'internal-step-id')
      })

      mockWsClient.sendMessage.mockClear()
      mockWsClient.rotate.mockClear()

      act(() => {
        vi.advanceTimersByTime(7_000)
      })

      expect(mockWsClient.rotate).not.toHaveBeenCalled()
      expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  test('does not replay or show an error when the ack timeout fires after switching conversations', () => {
    vi.useFakeTimers()
    try {
      mockStoreState.currentConversation = { id: 'conv-A', messages: [], userId: 'user-1' }
      mockWsClient.isConnected.mockReturnValue(true)
      mockWsClient.sendMessage.mockReturnValueOnce('outbound-original')

      const { result } = renderWebSocketHook()

      act(() => {
        result.current.sendMessage('Request from conv A')
      })

      mockStoreState.currentConversation = { id: 'conv-B', messages: [], userId: 'user-1' }
      mockWsClient.sendMessage.mockClear()
      mockWsClient.rotate.mockClear()
      mockAddErrorCard.mockClear()
      mockSetStreaming.mockClear()
      mockSetLoading.mockClear()

      act(() => {
        vi.advanceTimersByTime(7_000)
      })

      expect(mockWsClient.rotate).not.toHaveBeenCalled()
      expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
      expect(mockAddErrorCard).not.toHaveBeenCalled()
      expect(mockSetStreaming).not.toHaveBeenCalledWith(false)
      expect(mockSetLoading).not.toHaveBeenCalledWith(false)

      act(() => {
        capturedCallbacks.onConnectionChange?.('connected')
      })

      expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  test('fails closed when the replay also receives no backend frame before the ack timeout', () => {
    vi.useFakeTimers()
    try {
      mockWsClient.isConnected.mockReturnValue(true)
      mockWsClient.sendMessage
        .mockReturnValueOnce('outbound-original')
        .mockReturnValueOnce('outbound-replay')

      const { result } = renderWebSocketHook()

      act(() => {
        result.current.sendMessage('Request with repeated stale socket')
      })

      act(() => {
        vi.advanceTimersByTime(7_000)
      })
      act(() => {
        capturedCallbacks.onConnectionChange?.('connected')
      })

      mockWsClient.sendMessage.mockClear()
      mockWsClient.rotate.mockClear()
      mockSetStreaming.mockClear()
      mockSetLoading.mockClear()
      mockAddErrorCard.mockClear()

      act(() => {
        vi.advanceTimersByTime(7_000)
      })

      expect(mockWsClient.rotate).not.toHaveBeenCalled()
      expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
      expect(mockAddErrorCard).toHaveBeenCalledWith(
        'connection.failed',
        'No response received from the server. Please try again.',
      )
      expect(mockSetStreaming).toHaveBeenCalledWith(false)
      expect(mockSetLoading).toHaveBeenCalledWith(false)
    } finally {
      vi.useRealTimers()
    }
  })

  test('sendMessage does not add knowledge_layer when no files uploaded', async () => {
    mockWsClient.isConnected.mockReturnValue(true)

    // Mock layout store without knowledge_layer (it's filtered out by API client)
    const mockLayoutStore = await import('@/features/layout/store')
    vi.mocked(mockLayoutStore.useLayoutStore.getState).mockReturnValue({
      enabledDataSourceIds: ['web', 'docs'],
      knowledgeLayerAvailable: true,
    } as ReturnType<typeof mockLayoutStore.useLayoutStore.getState>)

    // Mock documents store with no files for this session
    const mockDocumentsStore = await import('@/features/documents/store')
    vi.mocked(mockDocumentsStore.useDocumentsStore.getState).mockReturnValue({
      trackedFiles: [],
    } as unknown as ReturnType<typeof mockDocumentsStore.useDocumentsStore.getState>)

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Hello')
    })

    // knowledge_layer should NOT be added since no files exist
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Hello', ['web', 'docs'])
  })

  test('sendMessage adds knowledge_layer when files are uploaded', async () => {
    mockWsClient.isConnected.mockReturnValue(true)

    // Mock layout store without knowledge_layer (it's filtered out by API client)
    const mockLayoutStore = await import('@/features/layout/store')
    vi.mocked(mockLayoutStore.useLayoutStore.getState).mockReturnValue({
      enabledDataSourceIds: ['web', 'docs'],
      knowledgeLayerAvailable: true,
    } as ReturnType<typeof mockLayoutStore.useLayoutStore.getState>)

    // Mock documents store with files for this session (status: success)
    const mockDocumentsStore = await import('@/features/documents/store')
    vi.mocked(mockDocumentsStore.useDocumentsStore.getState).mockReturnValue({
      trackedFiles: [
        { id: 'file-1', fileName: 'test.pdf', collectionName: 'conv-1', status: 'success', fileSize: 1000 },
      ],
    } as ReturnType<typeof mockDocumentsStore.useDocumentsStore.getState>)

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Hello')
    })

    // knowledge_layer should be ADDED since files exist for this session
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Hello', ['web', 'docs', 'knowledge_layer'])
  })

  test('sendMessage adds knowledge_layer when files are ingesting', async () => {
    mockWsClient.isConnected.mockReturnValue(true)

    // Mock layout store without knowledge_layer (it's filtered out by API client)
    const mockLayoutStore = await import('@/features/layout/store')
    vi.mocked(mockLayoutStore.useLayoutStore.getState).mockReturnValue({
      enabledDataSourceIds: ['web'],
      knowledgeLayerAvailable: true,
    } as ReturnType<typeof mockLayoutStore.useLayoutStore.getState>)

    // Mock documents store with files in ingesting state
    const mockDocumentsStore = await import('@/features/documents/store')
    vi.mocked(mockDocumentsStore.useDocumentsStore.getState).mockReturnValue({
      trackedFiles: [
        { id: 'file-1', fileName: 'test.pdf', collectionName: 'conv-1', status: 'ingesting', fileSize: 1000 },
      ],
    } as ReturnType<typeof mockDocumentsStore.useDocumentsStore.getState>)

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Hello')
    })

    // knowledge_layer should be ADDED since files are being ingested
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Hello', ['web', 'knowledge_layer'])
  })

  test('sendMessage does not add knowledge_layer when knowledgeLayerAvailable is false', async () => {
    mockWsClient.isConnected.mockReturnValue(true)

    // Mock layout store with knowledgeLayerAvailable: false
    const mockLayoutStore = await import('@/features/layout/store')
    vi.mocked(mockLayoutStore.useLayoutStore.getState).mockReturnValue({
      enabledDataSourceIds: ['web', 'docs'],
      knowledgeLayerAvailable: false,
    } as ReturnType<typeof mockLayoutStore.useLayoutStore.getState>)

    // Mock documents store with files (but knowledge layer not available)
    const mockDocumentsStore = await import('@/features/documents/store')
    vi.mocked(mockDocumentsStore.useDocumentsStore.getState).mockReturnValue({
      trackedFiles: [
        { id: 'file-1', fileName: 'test.pdf', collectionName: 'conv-1', status: 'success', fileSize: 1000 },
      ],
    } as ReturnType<typeof mockDocumentsStore.useDocumentsStore.getState>)

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.sendMessage('Hello')
    })

    // knowledge_layer should NOT be added even with files if knowledgeLayerAvailable is false
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Hello', ['web', 'docs'])
  })

  test('sendMessage sets error when WebSocket not connected and no conversation', () => {
    mockWsClient.isConnected.mockReturnValue(false)
    mockStoreState.currentConversation = null
    vi.mocked(useChatStore).getState = vi.fn(() => mockStoreState) as unknown as typeof useChatStore.getState

    const { result } = renderWebSocketHook({ autoConnect: false })

    act(() => {
      result.current.sendMessage('Hello')
    })

    expect(mockAddErrorCard).toHaveBeenCalledWith('system.unknown', 'No active conversation')
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
  })

  test('onResponse callback routes meta/shallow responses to chat', () => {
    // autoConnect: true creates the WebSocket client and captures callbacks
    renderWebSocketHook()

    // Both intermediate steps and the isFinal guard require isStreaming=true.
    mockStoreState.isStreaming = true

    // Simulate an intermediate step first to create a thinking step
    act(() => {
      capturedCallbacks.onIntermediateStep?.('Working...', 'in_progress')
    })

    vi.clearAllMocks()

    // Simulate final response
    act(() => {
      capturedCallbacks.onResponse?.('Response content', 'complete', true)
    })

    // Should complete the pending thinking step
    expect(mockCompleteThinkingStep).toHaveBeenCalledWith('step-1')
    // Note: reportContent is now only set by deep research SSE events, not by onResponse
    expect(mockAddAgentResponse).toHaveBeenCalledWith('Response content')
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetCurrentStatus).toHaveBeenCalledWith('complete')
  })

  test('onResponse callback adds streaming content to chat', () => {
    renderWebSocketHook()

    mockStoreState.isStreaming = true

    // Simulate streaming response (not final)
    act(() => {
      capturedCallbacks.onResponse?.('Partial content...', 'in_progress', false)
    })

    // Non-final responses with content are now added to chat as AgentResponse
    // reportContent is only set by deep research SSE events
    expect(mockAddAgentResponse).toHaveBeenCalledWith('Partial content...')
  })

  test('onResponse drops stale content when not streaming', () => {
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    renderWebSocketHook()

    mockStoreState.isStreaming = false

    act(() => {
      capturedCallbacks.onResponse?.('Repeated stale response', 'complete', true)
    })

    expect(mockAddAgentResponse).not.toHaveBeenCalled()
    expect(mockSetStreaming).not.toHaveBeenCalledWith(false)
    expect(consoleWarnSpy).toHaveBeenCalledWith('Ignoring stale isFinal -- not currently streaming')

    consoleWarnSpy.mockRestore()
  })

  test('onIntermediateStep callback creates thinking step if none exists', () => {
    renderWebSocketHook()

    // Intermediate steps are dropped when not streaming (stale-guard).
    mockStoreState.isStreaming = true

    // Simulate intermediate step with string content - no thinking step exists yet
    act(() => {
      capturedCallbacks.onIntermediateStep?.('Thinking...', 'in_progress')
    })

    // Should create a new thinking step with structured data
    expect(mockAddThinkingStep).toHaveBeenCalledWith({
      category: 'agents',
      functionName: 'unknown',
      displayName: 'Processing',
      content: 'Thinking...\n',
      isComplete: false,
    })
  })

  test('onIntermediateStep callback appends to existing thinking step', () => {
    renderWebSocketHook()

    // Intermediate steps are dropped when not streaming (stale-guard).
    mockStoreState.isStreaming = true

    // First call creates a step
    act(() => {
      capturedCallbacks.onIntermediateStep?.('First thought...', 'in_progress')
    })

    vi.clearAllMocks()

    // Second call with plain string creates another step (implementation doesn't append strings)
    act(() => {
      capturedCallbacks.onIntermediateStep?.('Second thought...', 'in_progress')
    })

    // Plain string intermediate steps each create a new step
    expect(mockAddThinkingStep).toHaveBeenCalledWith({
      category: 'agents',
      functionName: 'unknown',
      displayName: 'Processing',
      content: 'Second thought...\n',
      isComplete: false,
    })
  })

  test('onIntermediateStep callback handles object content with payload', () => {
    renderWebSocketHook()

    // Intermediate steps are dropped when not streaming (stale-guard).
    mockStoreState.isStreaming = true

    // Simulate intermediate step with object content - creates new step
    act(() => {
      capturedCallbacks.onIntermediateStep?.(
        { name: 'search_docs', payload: 'Searching documents...' },
        'in_progress'
      )
    })

    // Creates a new thinking step with structured data from parser
    expect(mockAddThinkingStep).toHaveBeenCalledWith(
      expect.objectContaining({
        functionName: 'search_docs',
        content: expect.any(String),
        isComplete: false,
      })
    )
  })

  test('onHumanPrompt callback sets pending interaction and adds prompt', () => {
    renderWebSocketHook()

    const mockPrompt = {
      input_type: 'text',
      text: 'Please clarify your question',
      options: undefined,
      default_value: undefined,
    }

    act(() => {
      capturedCallbacks.onHumanPrompt?.('prompt-1', 'parent-1', mockPrompt)
    })

    expect(mockSetPendingInteraction).toHaveBeenCalledWith({
      id: 'prompt-1',
      parentId: 'parent-1',
      inputType: 'text',
      text: 'Please clarify your question',
      options: undefined,
      defaultValue: undefined,
    })
    expect(mockAddAgentPrompt).toHaveBeenCalledWith(
      'text-input',
      'Please clarify your question',
      undefined,
      undefined,
      'prompt-1',
      'parent-1',
      'text'
    )
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('onError callback adds error card and resets state', () => {
    renderWebSocketHook()

    act(() => {
      capturedCallbacks.onError?.({
        code: 'invalid_message',
        message: 'Invalid message format',
        details: 'Missing required field',
      })
    })

    expect(mockAddErrorCard).toHaveBeenCalledWith(
      'agent.response_failed',
      'Invalid message format',
      'Missing required field'
    )
    expect(mockSetCurrentStatus).toHaveBeenCalledWith(null)
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('onConnectionChange callback updates connection state', () => {
    const { result } = renderWebSocketHook()

    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(result.current.isConnected).toBe(true)
  })

  test('onConnectionChange error updates state but does not add error card immediately', () => {
    renderWebSocketHook()

    act(() => {
      capturedCallbacks.onConnectionChange?.('error')
    })

    // Should NOT add error card immediately - wait for reconnection attempts
    expect(mockAddErrorCard).not.toHaveBeenCalled()
    // Should still update state
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('onError with CONNECTION_FAILED adds error card after reconnection attempts fail', async () => {
    mockCheckBackendHealthCached.mockResolvedValue(false)
    renderWebSocketHook()

    act(() => {
      capturedCallbacks.onError?.({
        code: 'CONNECTION_FAILED',
        message: 'Unable to connect to the server. Please check your network connection.',
      })
    })

    // Wait for the async health check to resolve before asserting
    await waitFor(() => {
      expect(mockAddErrorCard).toHaveBeenCalledWith(
        'connection.failed',
        'Unable to connect to the server. Please check your network connection.',
        undefined
      )
    })
  })

  test('respondToInteraction sends response via WebSocket', () => {
    mockWsClient.isConnected.mockReturnValue(true)
    mockStoreState.pendingInteraction = {
      id: 'prompt-1',
      parentId: 'parent-1',
      inputType: 'text',
      text: 'Clarify?',
    }
    mockStoreState.currentConversation = {
      id: 'conv-1',
      messages: [
        {
          id: 'msg-1',
          messageType: 'prompt',
          isPromptResponded: false,
          content: 'Question',
        },
      ],
      userId: 'user-1',
    }

    const { result } = renderWebSocketHook()

    act(() => {
      result.current.respondToInteraction('My response')
    })

    expect(mockRespondToPrompt).toHaveBeenCalledWith('msg-1', 'My response')
    expect(mockWsClient.sendInteractionResponse).toHaveBeenCalledWith(
      'prompt-1',
      'parent-1',
      'My response'
    )
    expect(mockSetStreaming).toHaveBeenCalledWith(true)
    expect(mockSetLoading).toHaveBeenCalledWith(true)
  })

  test('respondToInteraction warns when no pending interaction', () => {
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    mockStoreState.pendingInteraction = null

    const { result } = renderWebSocketHook({ autoConnect: false })

    act(() => {
      result.current.respondToInteraction('Response')
    })

    expect(consoleWarnSpy).toHaveBeenCalledWith('No pending interaction to respond to')
    expect(mockWsClient.sendInteractionResponse).not.toHaveBeenCalled()

    consoleWarnSpy.mockRestore()
  })

  test('createConversation calls store action', () => {
    const { result } = renderWebSocketHook({ autoConnect: false })

    act(() => {
      result.current.createConversation()
    })

    expect(mockCreateConversation).toHaveBeenCalled()
  })

  test('selectConversation calls store action with ID', () => {
    const { result } = renderWebSocketHook({ autoConnect: false })

    act(() => {
      result.current.selectConversation('conv-2')
    })

    expect(mockSelectConversation).toHaveBeenCalledWith('conv-2')
  })

  test('connect calls WebSocket connect', () => {
    const { result } = renderWebSocketHook()

    act(() => {
      result.current.connect()
    })

    expect(mockWsClient.connect).toHaveBeenCalled()
  })

  test('disconnect calls WebSocket disconnect and resets state', () => {
    const { result } = renderWebSocketHook()

    act(() => {
      result.current.disconnect()
    })

    expect(mockWsClient.disconnect).toHaveBeenCalled()
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
  })

  test('cleanup clears shallow streaming state when the socket unmounts mid-request', () => {
    mockStoreState.isStreaming = true
    mockStoreState.isLoading = true
    mockStoreState.currentStatus = 'thinking'

    const { unmount } = renderWebSocketHook()
    mockSetStreaming.mockClear()
    mockSetLoading.mockClear()
    mockSetCurrentStatus.mockClear()

    act(() => {
      unmount()
    })

    expect(mockWsClient.disconnect).toHaveBeenCalled()
    expect(mockSetStreaming).toHaveBeenCalledWith(false)
    expect(mockSetLoading).toHaveBeenCalledWith(false)
    expect(mockSetCurrentStatus).toHaveBeenCalledWith(null)
  })

  test('maps human prompt types correctly', () => {
    renderWebSocketHook()

    // Test multiple_choice -> choice
    act(() => {
      capturedCallbacks.onHumanPrompt?.('p1', 'parent', {
        input_type: 'multiple_choice',
        text: 'Choose one',
        options: ['A', 'B'],
      })
    })
    expect(mockAddAgentPrompt).toHaveBeenCalledWith('choice', 'Choose one', ['A', 'B'], undefined, 'p1', 'parent', 'multiple_choice')

    vi.clearAllMocks()

    // Test binary_choice -> approval
    act(() => {
      capturedCallbacks.onHumanPrompt?.('p2', 'parent', {
        input_type: 'binary_choice',
        text: 'Yes or no?',
      })
    })
    expect(mockAddAgentPrompt).toHaveBeenCalledWith('approval', 'Yes or no?', undefined, undefined, 'p2', 'parent', 'binary_choice')

    vi.clearAllMocks()

    // Test approval -> approval
    act(() => {
      capturedCallbacks.onHumanPrompt?.('p3', 'parent', {
        input_type: 'approval',
        text: 'Approve this?',
      })
    })
    expect(mockAddAgentPrompt).toHaveBeenCalledWith('approval', 'Approve this?', undefined, undefined, 'p3', 'parent', 'approval')

    vi.clearAllMocks()

    // Test unknown -> clarification
    act(() => {
      capturedCallbacks.onHumanPrompt?.('p4', 'parent', {
        input_type: 'unknown_type',
        text: 'Something else',
      })
    })
    expect(mockAddAgentPrompt).toHaveBeenCalledWith('clarification', 'Something else', undefined, undefined, 'p4', 'parent', 'unknown_type')
  })

  test('detects deep research escalation and starts SSE streaming', () => {
    const mockStartDeepResearch = vi.fn()
    const mockUpdateConversationTitle = vi.fn()
    const localMockAddAgentResponseWithMeta = vi.fn(() => 'msg-1')
    // Need to mock useChatStore to include startDeepResearch
    vi.mocked(useChatStore).mockImplementation((selector?: (s: any) => any) => {
      const state = {
        ...mockStoreState,
        addUserMessage: mockAddUserMessage,
        addAgentResponse: mockAddAgentResponse,
        addAgentResponseWithMeta: localMockAddAgentResponseWithMeta,
        addThinkingStep: mockAddThinkingStep,
        appendToThinkingStep: mockAppendToThinkingStep,
        completeThinkingStep: mockCompleteThinkingStep,
        updateThinkingStepByFunctionName: mockUpdateThinkingStepByFunctionName,
        findThinkingStepByFunctionName: mockFindThinkingStepByFunctionName,
        setReportContent: mockSetReportContent,
        addStatusCard: mockAddStatusCard,
        addAgentPrompt: mockAddAgentPrompt,
        addErrorCard: mockAddErrorCard,
        setCurrentStatus: mockSetCurrentStatus,
        setPendingInteraction: mockSetPendingInteraction,
        clearPendingInteraction: mockClearPendingInteraction,
        setLoading: mockSetLoading,
        setStreaming: mockSetStreaming,
        clearThinkingSteps: mockClearThinkingSteps,
        clearReportContent: mockClearReportContent,
        createConversation: mockCreateConversation,
        setCurrentUser: mockSetCurrentUser,
        getUserConversations: mockGetUserConversations,
        selectConversation: mockSelectConversation,
        respondToPrompt: mockRespondToPrompt,
        addPlanMessage: mockAddPlanMessage,
        updatePlanMessageResponse: mockUpdatePlanMessageResponse,
        addDeepResearchBanner: mockAddDeepResearchBanner,
        startDeepResearch: mockStartDeepResearch,
        updateConversationTitle: mockUpdateConversationTitle,
      }
      return selector ? selector(state) : state
    })

    renderWebSocketHook()
    mockStoreState.isStreaming = true

    // Simulate response with deep research escalation signal
    act(() => {
      capturedCallbacks.onResponse?.('Deep research job submitted. Job ID: abc123-def456', 'complete', false)
    })

    // Should detect deep research and call banner with 'starting' status
    expect(mockAddDeepResearchBanner).toHaveBeenCalledWith('starting', 'abc123-def456')
    // Should add tracking message with empty content and job metadata
    expect(localMockAddAgentResponseWithMeta).toHaveBeenCalledWith(
      '',
      false,
      expect.objectContaining({
        deepResearchJobId: 'abc123-def456',
        deepResearchJobStatus: 'submitted',
        isDeepResearchActive: true,
      })
    )
    expect(mockStartDeepResearch).toHaveBeenCalledWith('abc123-def456', 'msg-1')
  })
})

/**
 * Token rotation lifecycle.
 *
 * The hook must close + reopen the WebSocket before the token that
 * authenticated it expires. The backend only validates auth at the WS
 * upgrade, so a long-lived socket otherwise keeps trusting an expired token
 * forever. One timer + a deferred-rotation effect:
 *   - soft (-60s): if idle, rotate immediately. If streaming, mark
 *     `pendingRotationRef = true` and let the in-flight response finish.
 *   - deferred: when `isStreaming` transitions back to false, drain the
 *     pending flag and rotate. No banner, no resend -- silent refresh.
 *
 * Tests below drive `onBeforeReconnect` directly to seed the rotation
 * deadline (which mirrors what the real client would do during connect()),
 * then advance fake timers / mutate `isStreaming` to assert the policy.
 */
describe('useWebSocketChat -- token rotation', () => {
  const NOW_MS = 1_700_000_000_000 // arbitrary fixed wall clock
  /** Token expires 10 minutes from "now" -- soft fires at +9m. */
  const EXP_AT_S = Math.floor(NOW_MS / 1000) + 600
  const SOFT_DELAY_MS = 540_000 // 600s - 60s

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW_MS)
    // Restore default useChatStore mock impl in case a sibling test
    // overrode it (mockImplementation persists across tests, only
    // call counts are cleared by vi.clearAllMocks).
    vi.mocked(useChatStore).mockImplementation(defaultUseChatStoreImpl)
    vi.mocked(useAuth).mockReturnValue({
      user: { id: 'user-1', email: 'test@example.com' },
      idToken: 'mock-id-token',
      authRequired: true,
      isAuthenticated: true,
      isLoading: false,
      accessToken: undefined,
      error: undefined,
      signIn: vi.fn(),
      signOut: vi.fn(),
    })
    mockGetSession.mockResolvedValue({ idTokenExpiresAt: EXP_AT_S })
  })

  afterEach(() => {
    vi.useRealTimers()
    // Restore default useAuth so subsequent suites aren't affected.
    vi.mocked(useAuth).mockReturnValue({
      user: { id: 'user-1', email: 'test@example.com' },
      idToken: 'mock-id-token',
      authRequired: false,
      isAuthenticated: true,
      isLoading: false,
      accessToken: undefined,
      error: undefined,
      signIn: vi.fn(),
      signOut: vi.fn(),
    })
  })

  /**
   * Mounts the hook, drives `onBeforeReconnect` (which the real client invokes
   * inside connect()), and waits for the rotation timers to be armed.
   */
  async function mountAndArmTimers() {
    const rendered = renderWebSocketHook()
    // The real client calls onBeforeReconnect during connect(); the mock
    // doesn't, so do it manually to seed activeSocketTokenExpiresAt.
    await act(async () => {
      await capturedOnBeforeReconnect?.()
    })
    return rendered
  }

  test('soft timer rotates the socket when the chat is idle', async () => {
    await mountAndArmTimers()
    mockStoreState.isStreaming = false
    mockWsClient.rotate.mockClear()
    mockWsClient.disconnect.mockClear()
    mockWsClient.connect.mockClear()

    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS)
    })

    // Rotation goes through the atomic client.rotate() primitive -- NOT
    // the disconnect()+connect() interleave, which has the onclose race
    // (see NATWebSocketClient.rotate() docstring).
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    expect(mockWsClient.disconnect).not.toHaveBeenCalled()
    // Idle rotation must be silent -- no error/banner is shown to the user.
    expect(mockAddErrorCard).not.toHaveBeenCalled()
    expect(mockSetStreaming).not.toHaveBeenCalledWith(false)
  })

  test('soft timer does NOT rotate when a stream is in flight (defer until done)', async () => {
    const { rerender } = await mountAndArmTimers()

    // Mark streaming and rerender so the hook's deferred-rotation effect
    // observes the true -> false transition later. Without this rerender
    // the hook's local `isStreaming` selector value never flips to true,
    // so the eventual flip back to false wouldn't be a transition either.
    mockStoreState.isStreaming = true
    await act(async () => {
      rerender()
    })

    mockWsClient.rotate.mockClear()
    mockWsClient.disconnect.mockClear()
    mockWsClient.connect.mockClear()

    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS)
    })

    // Soft timer fired and was deferred -- in-flight stream is preserved.
    // Critically, no banner: the user should not see a "session expired"
    // message just because the rotation timer fired.
    expect(mockWsClient.rotate).not.toHaveBeenCalled()
    expect(mockWsClient.disconnect).not.toHaveBeenCalled()
    expect(mockAddErrorCard).not.toHaveBeenCalled()
    // No premature stream cleanup either: setStreaming(false) must NOT have
    // been called as a side-effect of the rotation timer.
    expect(mockSetStreaming).not.toHaveBeenCalledWith(false)

    // Stream finishes -> the deferred rotation effect picks up the flag
    // and rotates silently.
    mockStoreState.isStreaming = false
    await act(async () => {
      rerender()
    })

    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    expect(mockWsClient.disconnect).not.toHaveBeenCalled()
    expect(mockAddErrorCard).not.toHaveBeenCalled()
  })

  test('rotation cycle invokes getSession exactly once (no SessionProvider race)', async () => {
    await mountAndArmTimers()
    // Initial mount counts as one getSession call (the connect path's
    // refreshAuthBeforeReconnect). Reset and verify a single rotation cycle
    // adds exactly one more call -- proving we don't accidentally fan out
    // refreshes (which would cause invalid_grant with rotating refresh tokens).
    mockGetSession.mockClear()
    mockStoreState.isStreaming = false

    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS)
    })

    // The mocked client.connect() is a no-op -- it does NOT re-invoke
    // onBeforeReconnect like the real one would. So we manually drive the
    // post-rotation refresh here and assert getSession was only called once.
    await act(async () => {
      await capturedOnBeforeReconnect?.()
    })

    expect(mockGetSession).toHaveBeenCalledTimes(1)
  })

  test('updated idTokenExpiresAt re-arms timers; old timers do not double-fire', async () => {
    await mountAndArmTimers()
    mockStoreState.isStreaming = false
    mockWsClient.rotate.mockClear()
    mockWsClient.disconnect.mockClear()
    mockWsClient.connect.mockClear()

    // Refresh returns a NEW expiry far in the future. This should re-run the
    // effect, clear the old timers, and arm new ones.
    const NEW_EXP_AT_S = Math.floor(NOW_MS / 1000) + 1200
    mockGetSession.mockResolvedValue({ idTokenExpiresAt: NEW_EXP_AT_S })
    await act(async () => {
      await capturedOnBeforeReconnect?.()
    })

    // Original soft deadline -- old timer would have fired here, but it was
    // cleaned up by the effect's cleanup function. The new soft deadline is
    // 1140s from NOW.
    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS)
    })

    expect(mockWsClient.rotate).not.toHaveBeenCalled()

    // Advance to the new soft deadline; rotation should fire exactly once.
    const NEW_SOFT_DELAY_MS = 1_140_000 - SOFT_DELAY_MS
    await act(async () => {
      vi.advanceTimersByTime(NEW_SOFT_DELAY_MS)
    })

    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
  })

  test('failed getSession does not crash and leaves prior timers intact', async () => {
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await mountAndArmTimers()
    mockStoreState.isStreaming = false
    mockWsClient.rotate.mockClear()
    mockWsClient.disconnect.mockClear()
    mockWsClient.connect.mockClear()

    // Subsequent refresh fails (e.g. transient network blip).
    mockGetSession.mockRejectedValueOnce(new Error('network down'))
    await act(async () => {
      await capturedOnBeforeReconnect?.()
    })

    // Old timers were armed against the FIRST successful getSession's expiry.
    // They should still fire on schedule even though the second refresh failed.
    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS)
    })

    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining('getSession before WS reconnect failed'),
      expect.any(Error)
    )
    consoleWarnSpy.mockRestore()
  })

  test('does not arm rotation timer when authRequired is false', async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: 'user-1', email: 'test@example.com' },
      idToken: undefined,
      authRequired: false,
      isAuthenticated: true,
      isLoading: false,
      accessToken: undefined,
      error: undefined,
      signIn: vi.fn(),
      signOut: vi.fn(),
    })
    renderWebSocketHook()
    await act(async () => {
      await capturedOnBeforeReconnect?.()
    })
    mockWsClient.rotate.mockClear()
    mockWsClient.disconnect.mockClear()
    mockWsClient.connect.mockClear()

    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS + 60_000)
    })

    expect(mockWsClient.rotate).not.toHaveBeenCalled()
    // refreshAuthBeforeReconnect short-circuits when !authRequired, so
    // getSession should never be called.
    expect(mockGetSession).not.toHaveBeenCalled()
  })

  test('cleanup on unmount cancels the pending soft timer', async () => {
    const { unmount } = await mountAndArmTimers()
    mockStoreState.isStreaming = false
    mockWsClient.rotate.mockClear()
    mockWsClient.disconnect.mockClear()
    mockWsClient.connect.mockClear()

    unmount()

    await act(async () => {
      vi.advanceTimersByTime(SOFT_DELAY_MS + 60_000)
    })

    // The unmount-triggered conversation-cleanup useEffect calls disconnect()
    // exactly once. Crucially, NO rotation should fire from the rotation
    // timer after unmount.
    expect(mockWsClient.disconnect).toHaveBeenCalledTimes(1)
    expect(mockWsClient.rotate).not.toHaveBeenCalled()
  })

  /**
   * Pre-flight check: a long-idle socket may technically be connected, but
   * if the JWT that authenticated it has already expired (e.g. after a
   * laptop sleep), `sendMessage` must NOT push the message through that
   * socket. Instead, it should buffer the outgoing payload, rotate the
   * socket, and have the new `onConnectionChange('connected')` handler
   * drain the buffer once the fresh handshake completes.
   */
  test('sendMessage with stale token rotates socket and drains buffer on connect', async () => {
    // mountAndArmTimers seeds activeSocketTokenExpiresAt to EXP_AT_S via
    // the captured onBeforeReconnect call.
    const { result } = await mountAndArmTimers()

    // Move the wall clock past expiry. The soft timer was armed for SOFT_DELAY_MS
    // from NOW_MS, so it has NOT fired yet -- but the token is already dead
    // because real time advanced (e.g. the tab was suspended).
    vi.setSystemTime(EXP_AT_S * 1000 + 1)

    // Socket is "connected" but the underlying token is already past `exp`.
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()

    act(() => {
      result.current.sendMessage('Hello after long idle')
    })

    // Pre-flight: must NOT send through the stale socket. Instead,
    // rotate the connection so the new handshake carries a fresh cookie.
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)

    // Simulate the handshake completing: the captured onConnectionChange
    // is invoked with 'connected' and should drain the buffered message.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledWith(
      'Hello after long idle',
      expect.any(Array)
    )
    // No banner -- the rotation was completely silent for the user.
    expect(mockAddErrorCard).not.toHaveBeenCalled()
  })

  test('sendMessage with valid token sends directly without rotating', async () => {
    const { result } = await mountAndArmTimers()
    // Token still valid (10min in the future). No pre-flight rotation.
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()

    act(() => {
      result.current.sendMessage('Hello')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Hello', expect.any(Array))
    expect(mockWsClient.rotate).not.toHaveBeenCalled()
  })

  /**
   * `auth_expired` from the backend (per-message JWT re-auth on the WS
   * handler) must NOT bubble up to the user as an error. The hook should:
   *   1. NOT show a banner (no addErrorCard call)
   *   2. Buffer the just-sent payload (lastSentOutgoingRef -> pendingOutgoingRef)
   *   3. Rotate the socket so the new handshake reads a fresh idToken
   *   4. On 'connected', drain the buffer and re-issue the original message
   * Net effect for the user: brief reconnect, then their answer arrives.
   */
  test('auth_expired error triggers silent reconnect + auto-resend of last message', async () => {
    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    // Send a message so lastSentOutgoingRef is populated. doSend() captures
    // both the content and the resolved data sources, mirroring what the
    // user actually saw on the wire.
    act(() => {
      result.current.sendMessage('What is the weather?')
    })
    expect(mockWsClient.sendMessage).toHaveBeenLastCalledWith('What is the weather?', expect.any(Array))

    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()
    // Reset streaming/loading mocks so we only assert on post-error calls
    // (sendMessage already drove them through their normal start-of-request
    // sequence).
    mockSetStreaming.mockClear()
    mockSetLoading.mockClear()

    // Backend rejects mid-workflow with auth_expired (handshake JWT past exp).
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
        details: 'Handshake token has expired',
      })
    })

    // No banner: this is the whole point -- silent for the user.
    expect(mockAddErrorCard).not.toHaveBeenCalled()
    // Streaming/loading state must NOT be reset by onError -- the user's
    // "request in progress" UX should bridge the rotation seamlessly.
    // (The drain on 'connected' will eventually clear loading; for the
    // onError step itself nothing should fire.)
    expect(mockSetStreaming).not.toHaveBeenCalled()
    expect(mockSetLoading).not.toHaveBeenCalled()
    // Rotation kicked off via the atomic client.rotate() primitive.
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)

    // Simulate the new handshake completing -> drain buffered message.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })

    expect(mockWsClient.sendMessage).toHaveBeenCalledWith(
      'What is the weather?',
      expect.any(Array)
    )
  })

  /**
   * Regression: an `auth_expired` rotation that fails (CONNECTION_FAILED)
   * must drop `pendingOutgoingRef`. Otherwise, when the connection later
   * recovers via `useConnectionRecovery`, the stale buffered message would
   * be silently re-sent at a point where the UI has already shown the user
   * a failure state -- a "phantom resend" the user never asked for.
   */
  test('auth_expired -> CONNECTION_FAILED clears resend buffer (no phantom resend on recovery)', async () => {
    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    act(() => {
      result.current.sendMessage('Original question')
    })

    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    // Backend rejects with auth_expired -- buffer is populated and rotation kicks off.
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)

    // Rotation cannot recover -- WS client exhausts retries and emits
    // CONNECTION_FAILED. UI shows a failure card to the user.
    mockCheckBackendHealthCached.mockResolvedValue(true)
    await act(async () => {
      await capturedCallbacks.onError?.({
        code: 'CONNECTION_FAILED',
        message: 'Unable to connect to the server.',
      })
    })
    expect(mockAddErrorCard).toHaveBeenCalled()

    mockWsClient.sendMessage.mockClear()

    // Later, useConnectionRecovery polls health and the connection comes
    // back. The 'connected' transition must NOT replay the original
    // message: the user has already seen the failure and may have moved
    // on. A silent resend at this point would be the bug.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  test('non-auth_expired error still surfaces an error card and clears resend buffer', async () => {
    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    act(() => {
      result.current.sendMessage('Hello')
    })

    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    // Generic backend error (NOT auth_expired) -- must show a banner
    // and must NOT trigger a silent rotation.
    act(() => {
      capturedCallbacks.onError?.({
        code: 'workflow_error',
        message: 'Something broke in the agent',
      })
    })

    expect(mockAddErrorCard).toHaveBeenCalled()
    expect(mockWsClient.rotate).not.toHaveBeenCalled()

    // After this generic error, an unrelated 'connected' event (e.g. a
    // routine soft rotation) must NOT replay the message: that would be
    // a phantom resend the user never asked for.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  /**
   * Regression: the auth_expired guard must require BOTH the documented
   * backend fields (`code === 'user_auth_error'` and `message ===
   * 'auth_expired'`). An unrelated agent/workflow error that happens to
   * carry `message: 'auth_expired'` (e.g. user-facing text from a tool)
   * must surface as an error card, not silently trigger a phantom
   * reconnect that masks the real failure.
   */
  test('error with auth_expired message but non-auth code surfaces a banner (no silent reconnect)', async () => {
    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    act(() => {
      result.current.sendMessage('Hello')
    })

    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    act(() => {
      capturedCallbacks.onError?.({
        code: 'workflow_error',
        message: 'auth_expired',
      })
    })

    // Must be treated as a generic application error: banner shown, NO
    // rotation, NO drain on the next 'connected'.
    expect(mockAddErrorCard).toHaveBeenCalled()
    expect(mockWsClient.rotate).not.toHaveBeenCalled()

    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  /**
   * Regression: a pre-flight rotation that drains the buffer must update
   * `lastSentOutgoingRef`, so a follow-up `auth_expired` on the freshly
   * rotated socket can re-buffer the same payload. Without this, the
   * second auth_expired finds `lastSentOutgoingRef === null` and the
   * user's message is silently dropped (no error card, no resend).
   */
  test('preflight rotation -> drain -> auth_expired chains the resend (no silent loss)', async () => {
    const { result } = await mountAndArmTimers()

    // Move past expiry so the preflight branch fires inside sendMessage.
    vi.setSystemTime(EXP_AT_S * 1000 + 1)
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()

    act(() => {
      result.current.sendMessage('Pre-flight payload')
    })

    // Pre-flight: buffered, rotation kicked off, NOT yet on the wire.
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)

    // Fresh socket connects -> drain puts the buffered payload on the wire.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Pre-flight payload', expect.any(Array))

    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    // The fresh socket ALSO comes back with auth_expired (e.g. a NextAuth
    // refresh race left two stale tokens in a row). The handler must be
    // able to re-buffer the same payload via lastSentOutgoingRef -- which
    // the drain block is responsible for populating.
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    // Critically: silent for the user. No banner.
    expect(mockAddErrorCard).not.toHaveBeenCalled()

    // Second drain must put the SAME payload back on the wire. If the
    // drain block forgot to populate lastSentOutgoingRef, this assertion
    // fails and the user's message is silently lost.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).toHaveBeenCalledWith('Pre-flight payload', expect.any(Array))
  })

  /**
   * Regression for the HITL `auth_expired` gap: the backend applies the
   * same per-message expiry gate to `WebSocketUserInteractionResponseMessage`
   * as it does to chat messages. If the user answers a HITL prompt right
   * after the handshake token expires, `respondToInteraction()` used to
   * bypass the rotation buffer entirely: it sent directly through
   * `sendInteractionResponse()`, never populating `lastSentOutgoingRef`.
   * The auth_expired handler would then either replay the previous chat
   * message OR (if no prior chat existed) rotate with an empty buffer --
   * silently losing the user's answer.
   *
   * The fix mirrors `sendMessage`'s rotation handling: record the HITL
   * payload in `lastSentOutgoingRef` after a successful send, and let
   * `onError(auth_expired)` re-buffer it for the post-rotation drain.
   */
  test('respondToInteraction + auth_expired re-issues the HITL response (not lost, not replaced)', async () => {
    mockStoreState.pendingInteraction = {
      id: 'prompt-1',
      parentId: 'parent-1',
      inputType: 'text',
      text: 'Clarify your question?',
    }
    mockStoreState.currentConversation = {
      id: 'conv-1',
      messages: [
        {
          id: 'msg-1',
          messageType: 'prompt',
          isPromptResponded: false,
          content: 'Clarify your question?',
        },
      ],
      userId: 'user-1',
    }

    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendInteractionResponse.mockClear()
    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    // User answers the HITL prompt -- normal connected path.
    act(() => {
      result.current.respondToInteraction('Yes, proceed with option A')
    })
    expect(mockWsClient.sendInteractionResponse).toHaveBeenCalledWith(
      'prompt-1',
      'parent-1',
      'Yes, proceed with option A'
    )

    mockWsClient.sendInteractionResponse.mockClear()
    mockWsClient.sendMessage.mockClear()

    // Backend rejects mid-workflow with auth_expired -- the per-message
    // re-auth gate fired on the HITL response.
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })

    // Silent rotation, no banner.
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    expect(mockAddErrorCard).not.toHaveBeenCalled()

    // Fresh socket connects -> drain MUST re-issue the HITL response
    // (NOT sendMessage of a stale chat payload).
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendInteractionResponse).toHaveBeenCalledWith(
      'prompt-1',
      'parent-1',
      'Yes, proceed with option A'
    )
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  /**
   * Regression for the cross-payload poisoning case: previously the
   * resend buffer only tracked chat messages, so a HITL answer after a
   * previously-sent chat message would replay the OLD chat message on
   * auth_expired, not the user's HITL response. With the discriminated
   * union, the HITL send overwrites `lastSentOutgoingRef` and the drain
   * dispatches by `kind`.
   */
  test('HITL response after a chat send replays the HITL on auth_expired (no cross-payload poisoning)', async () => {
    mockStoreState.pendingInteraction = {
      id: 'prompt-2',
      parentId: 'parent-2',
      inputType: 'text',
      text: 'Need more detail?',
    }
    mockStoreState.currentConversation = {
      id: 'conv-1',
      messages: [
        {
          id: 'msg-1',
          messageType: 'prompt',
          isPromptResponded: false,
          content: 'Need more detail?',
        },
      ],
      userId: 'user-1',
    }

    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    // 1) Earlier chat send populates lastSentOutgoingRef with a 'message' payload.
    act(() => {
      result.current.sendMessage('Original chat question')
    })
    expect(mockWsClient.sendMessage).toHaveBeenLastCalledWith('Original chat question', expect.any(Array))

    mockWsClient.sendMessage.mockClear()
    mockWsClient.sendInteractionResponse.mockClear()
    mockWsClient.rotate.mockClear()

    // 2) HITL response on the same socket -- must OVERWRITE lastSentOutgoingRef.
    act(() => {
      result.current.respondToInteraction('Yes, full report please')
    })
    expect(mockWsClient.sendInteractionResponse).toHaveBeenCalledWith(
      'prompt-2',
      'parent-2',
      'Yes, full report please'
    )

    mockWsClient.sendInteractionResponse.mockClear()

    // 3) Backend returns auth_expired AFTER the HITL response.
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })

    // 4) Drain MUST replay the HITL response, not the earlier chat message.
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendInteractionResponse).toHaveBeenCalledWith(
      'prompt-2',
      'parent-2',
      'Yes, full report please'
    )
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  /**
   * Regression for the silent-rotation-loop class of bug.
   *
   * `rotate()` resets `reconnectCount` to 0 inside the WS client, so the
   * client's own CONNECTION_FAILED safety net never trips on the
   * auth_expired path. Without an explicit cap in the hook, a
   * stale-NextAuth-cache or clock-skew condition where `getSession()`
   * keeps returning the same already-expired JWT can drive dozens of
   * silent rotations per minute: the user just stares at a spinner that
   * never resolves and the server is forced to churn handshake slots.
   *
   * The cap bails after MAX_CONSECUTIVE_AUTH_EXPIRED rotations, clears
   * both resend buffers, and surfaces `auth.session_expired` so the user
   * can re-sign-in.
   */
  test('cap on consecutive auth_expired surfaces session_expired after 3 rotations', async () => {
    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    act(() => {
      result.current.sendMessage('What is X?')
    })
    expect(mockWsClient.sendMessage).toHaveBeenLastCalledWith('What is X?', expect.any(Array))

    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    const triggerAuthExpired = () => {
      act(() => {
        capturedCallbacks.onError?.({
          code: 'user_auth_error',
          message: 'auth_expired',
        })
      })
    }

    // First three auth_expired errors: rotate silently as designed --
    // this is the normal silent-reconnect path users rely on.
    triggerAuthExpired()
    triggerAuthExpired()
    triggerAuthExpired()
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(3)
    expect(mockAddErrorCard).not.toHaveBeenCalled()

    mockWsClient.rotate.mockClear()

    // Fourth in a row: bail out. Banner up, NO more rotate, buffers
    // cleared so a later recovery-driven 'connected' doesn't quietly
    // replay the original payload.
    triggerAuthExpired()

    expect(mockWsClient.rotate).not.toHaveBeenCalled()
    expect(mockAddErrorCard).toHaveBeenCalledWith(
      'auth.session_expired',
      expect.stringMatching(/sign in/i),
      undefined,
    )

    mockWsClient.sendMessage.mockClear()
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  /**
   * The consecutive-auth_expired counter must reset on ANY successful
   * frame from the backend. A passing response proves the post-rotation
   * auth is alive, so a subsequent, independent auth_expired (e.g.
   * the *next* JWT also expiring later in the session) starts a fresh
   * silent-reconnect budget -- it must not inherit the previous run's
   * counter and trip the cap prematurely.
   */
  test('successful response between auth_expired errors resets the rotation budget', async () => {
    const { result } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    act(() => {
      result.current.sendMessage('Q1')
    })

    mockWsClient.rotate.mockClear()
    mockAddErrorCard.mockClear()

    // 3 in a row -- right at the cap, still silent.
    for (let i = 0; i < 3; i++) {
      act(() => {
        capturedCallbacks.onError?.({
          code: 'user_auth_error',
          message: 'auth_expired',
        })
      })
    }
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(3)
    expect(mockAddErrorCard).not.toHaveBeenCalled()

    // A response arrives -- the latest rotation succeeded after all.
    // onResponse's stale guard requires isStreaming=true.
    mockStoreState.isStreaming = true
    act(() => {
      capturedCallbacks.onResponse?.('Here is the answer', 'in_progress', false)
    })

    mockWsClient.rotate.mockClear()

    // An independent auth_expired much later in the session must rotate
    // silently again (NOT surface the banner from the previous run's
    // counter).
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    expect(mockAddErrorCard).not.toHaveBeenCalled()
  })

  /**
   * Regression for cross-conversation data leak.
   *
   * The resend buffers (`pendingOutgoingRef`, `lastSentOutgoingRef`)
   * and the consecutive-auth_expired counter are conversation-scoped.
   * If left intact when the user switches conversations, the next
   * conversation's freshly-handshaken socket would drain the previous
   * conversation's payload into its own backend session on the first
   * `connected` event -- delivering user-typed content (chat message
   * or HITL response) to the wrong conversation's backend context.
   *
   * The conversation-switch cleanup must wipe both buffers, so the new
   * conversation starts with a clean slate.
   */
  test('switching conversations clears resend buffers (no cross-conversation drain)', async () => {
    mockStoreState.currentConversation = { id: 'conv-A', messages: [], userId: 'user-1' }

    const { result, rerender } = await mountAndArmTimers()
    mockWsClient.isConnected.mockReturnValue(true)

    // 1) In conv A, send a message and let it through. lastSentOutgoingRef
    //    is now populated with conv A's payload.
    act(() => {
      result.current.sendMessage('Secret payload for conv A')
    })
    expect(mockWsClient.sendMessage).toHaveBeenLastCalledWith(
      'Secret payload for conv A',
      expect.any(Array),
    )

    // 2) Backend rejects with auth_expired -- pendingOutgoingRef is
    //    populated (copied from lastSentOutgoingRef), rotation kicks off.
    //    At this point BOTH buffers carry conv A's payload.
    mockWsClient.sendMessage.mockClear()
    mockWsClient.rotate.mockClear()
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)

    // 3) BEFORE the post-rotation 'connected' drain fires, the user
    //    switches to conv B. The conversation-switch cleanup must wipe
    //    both buffers; otherwise conv B's first `connected` would
    //    silently submit conv A's payload to conv B's session.
    mockStoreState.currentConversation = { id: 'conv-B', messages: [], userId: 'user-1' }
    await act(async () => {
      rerender()
    })

    // 4) Conv B's fresh socket connects. The drain MUST be a no-op:
    //    pendingOutgoingRef is null, so neither sendMessage nor
    //    sendInteractionResponse fire. Conv A's payload stays in conv A.
    mockWsClient.sendMessage.mockClear()
    mockWsClient.sendInteractionResponse.mockClear()
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    expect(mockWsClient.sendInteractionResponse).not.toHaveBeenCalled()

    // 5) An auth_expired arriving on conv B's socket must also be unable
    //    to re-buffer conv A's payload (lastSentOutgoingRef was cleared
    //    too). Without that ref, the auth_expired handler simply rotates
    //    with no buffer -- no cross-conversation poisoning.
    mockWsClient.rotate.mockClear()
    act(() => {
      capturedCallbacks.onError?.({
        code: 'user_auth_error',
        message: 'auth_expired',
      })
    })
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)

    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
  })

  /**
   * Stale-token preflight applies to HITL responses too. If the socket
   * still reports connected but its JWT is already past `exp`, the
   * backend will reject the answer. respondToInteraction must buffer the
   * payload, rotate, and let the drain re-issue it -- exactly as
   * sendMessage does.
   */
  test('respondToInteraction with stale token rotates and drains the HITL response', async () => {
    mockStoreState.pendingInteraction = {
      id: 'prompt-3',
      parentId: 'parent-3',
      inputType: 'text',
      text: 'Confirm?',
    }
    mockStoreState.currentConversation = {
      id: 'conv-1',
      messages: [
        {
          id: 'msg-1',
          messageType: 'prompt',
          isPromptResponded: false,
          content: 'Confirm?',
        },
      ],
      userId: 'user-1',
    }

    const { result } = await mountAndArmTimers()

    // Move past expiry so the preflight branch fires.
    vi.setSystemTime(EXP_AT_S * 1000 + 1)
    mockWsClient.isConnected.mockReturnValue(true)
    mockWsClient.sendInteractionResponse.mockClear()
    mockWsClient.rotate.mockClear()

    act(() => {
      result.current.respondToInteraction('Yes, confirmed')
    })

    // Preflight: rotate kicked off, response NOT yet on the wire.
    expect(mockWsClient.sendInteractionResponse).not.toHaveBeenCalled()
    expect(mockWsClient.rotate).toHaveBeenCalledTimes(1)
    mockSetLoading.mockClear()

    // Fresh socket connects -> drain dispatches via sendInteractionResponse,
    // NOT sendMessage. The HITL loading state should stay active while the
    // backend processes the answer, matching respondToInteraction.doSend().
    act(() => {
      capturedCallbacks.onConnectionChange?.('connected')
    })
    expect(mockWsClient.sendInteractionResponse).toHaveBeenCalledWith(
      'prompt-3',
      'parent-3',
      'Yes, confirmed'
    )
    expect(mockWsClient.sendMessage).not.toHaveBeenCalled()
    expect(mockSetLoading).toHaveBeenCalledWith(true)
  })
})
