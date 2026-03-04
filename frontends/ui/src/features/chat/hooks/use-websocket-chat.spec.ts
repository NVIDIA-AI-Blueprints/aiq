// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act, waitFor } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { useWebSocketChat } from './use-websocket-chat'

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

vi.mock('../store', () => ({
  useChatStore: Object.assign(
    vi.fn(() => ({
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
    })),
    {
      getState: vi.fn(() => ({
        ...mockStoreState,
      })),
    }
  ),
  selectHasConnectionError: () => false,
}))

// Mock auth hook
vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({
    user: { id: 'user-1', email: 'test@example.com' },
    idToken: 'mock-id-token',
  })),
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
  useLayoutStore: Object.assign(vi.fn(() => ({})), {
    getState: vi.fn(() => ({
      enabledDataSourceIds: ['source-1', 'source-2'],
    })),
  }),
}))

// Mock documents store
vi.mock('@/features/documents/store', () => ({
  useDocumentsStore: Object.assign(vi.fn(() => ({})), {
    getState: vi.fn(() => ({
      trackedFiles: [],
    })),
  }),
}))

// Mock WebSocket client
const mockWsClient = {
  connect: vi.fn(),
  disconnect: vi.fn(),
  sendMessage: vi.fn(),
  sendInteractionResponse: vi.fn(),
  isConnected: vi.fn(() => false),
  updateAuthToken: vi.fn(),
  updateConversationId: vi.fn(),
}

let capturedCallbacks: {
  onResponse?: (content: string, status: string, isFinal: boolean) => void
  onIntermediateStep?: (content: unknown, status: string) => void
  onHumanPrompt?: (promptId: string, parentId: string, prompt: unknown) => void
  onError?: (error: { code: string; message: string; details?: string }) => void
  onConnectionChange?: (status: string) => void
} = {}

vi.mock('@/adapters/api/websocket-client', () => ({
  createNATWebSocketClient: vi.fn((options: { callbacks: typeof capturedCallbacks }) => {
    capturedCallbacks = options.callbacks
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

    // Simulate streaming response (not final)
    act(() => {
      capturedCallbacks.onResponse?.('Partial content...', 'in_progress', false)
    })

    // Non-final responses with content are now added to chat as AgentResponse
    // reportContent is only set by deep research SSE events
    expect(mockAddAgentResponse).toHaveBeenCalledWith('Partial content...')
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
    vi.mocked(useChatStore).mockReturnValue({
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
    } as unknown as ReturnType<typeof useChatStore>)

    renderWebSocketHook()

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
