// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { useLoadJobData } from './use-load-job-data'
import { useChatStore } from '../store'
import type { ChatMessage, Conversation } from '../types'

const mockGetJobStatus = vi.fn()
const mockGetJobReport = vi.fn()
const mockGetJobState = vi.fn()
const mockCreateDeepResearchClient = vi.fn()
const mockSetReportContent = vi.fn()
const mockAddDeepResearchToolCall = vi.fn()
const mockCompleteDeepResearchToolCall = vi.fn()
const mockClearDeepResearch = vi.fn()
const mockSetCurrentStatus = vi.fn()
const mockSetLoadedJobId = vi.fn()
const mockSetStreamLoaded = vi.fn()
const mockStopAllDeepResearchSpinners = vi.fn()
const mockAddErrorCard = vi.fn()
const mockCompleteDeepResearch = vi.fn()
const mockSetStreaming = vi.fn()
const mockPatchConversationMessage = vi.fn()
const mockAddDeepResearchBanner = vi.fn()
const mockOpenRightPanel = vi.fn()
const mockSetResearchPanelTab = vi.fn()

type MockConversation = Pick<Conversation, 'id' | 'messages'>

const createDefaultMessages = (): ChatMessage[] => [
  {
    id: 'tracking-msg',
    role: 'assistant',
    content: '',
    timestamp: new Date(),
    messageType: 'agent_response',
    deepResearchJobId: 'job-404',
    deepResearchJobStatus: 'running',
    isDeepResearchActive: true,
  },
  {
    id: 'starting-banner',
    role: 'assistant',
    content: '',
    timestamp: new Date(),
    messageType: 'deep_research_banner',
    deepResearchBannerData: { bannerType: 'starting', jobId: 'job-404' },
  },
]

let mockStoreState: {
  currentConversation: MockConversation | null
  conversations: MockConversation[]
  deepResearchJobId: string | null
  deepResearchStreamLoaded: boolean
  reportContent: string
  isDeepResearchStreaming: boolean
} = {
  currentConversation: {
    id: 'conv-1',
    messages: createDefaultMessages(),
  },
  conversations: [],
  deepResearchJobId: null as string | null,
  deepResearchStreamLoaded: false,
  reportContent: '',
  isDeepResearchStreaming: false,
}

type MockChatSelectorState = {
  setReportContent: typeof mockSetReportContent
  addDeepResearchToolCall: typeof mockAddDeepResearchToolCall
  completeDeepResearchToolCall: typeof mockCompleteDeepResearchToolCall
  clearDeepResearch: typeof mockClearDeepResearch
  setCurrentStatus: typeof mockSetCurrentStatus
  setLoadedJobId: typeof mockSetLoadedJobId
  setStreamLoaded: typeof mockSetStreamLoaded
  stopAllDeepResearchSpinners: typeof mockStopAllDeepResearchSpinners
  addErrorCard: typeof mockAddErrorCard
  completeDeepResearch: typeof mockCompleteDeepResearch
  setStreaming: typeof mockSetStreaming
  patchConversationMessage: typeof mockPatchConversationMessage
  addDeepResearchBanner: typeof mockAddDeepResearchBanner
}

type MockLayoutSelectorState = {
  openRightPanel: typeof mockOpenRightPanel
  setResearchPanelTab: typeof mockSetResearchPanelTab
}

vi.mock('@/adapters/api', () => ({
  getJobStatus: (...args: unknown[]) => mockGetJobStatus(...args),
  getJobReport: (...args: unknown[]) => mockGetJobReport(...args),
  getJobState: (...args: unknown[]) => mockGetJobState(...args),
  createDeepResearchClient: (...args: unknown[]) => mockCreateDeepResearchClient(...args),
}))

vi.mock('../store', () => ({
  useChatStore: Object.assign(
    vi.fn((selector?: (s: MockChatSelectorState) => unknown) => {
      const state: MockChatSelectorState = {
        setReportContent: mockSetReportContent,
        addDeepResearchToolCall: mockAddDeepResearchToolCall,
        completeDeepResearchToolCall: mockCompleteDeepResearchToolCall,
        clearDeepResearch: mockClearDeepResearch,
        setCurrentStatus: mockSetCurrentStatus,
        setLoadedJobId: mockSetLoadedJobId,
        setStreamLoaded: mockSetStreamLoaded,
        stopAllDeepResearchSpinners: mockStopAllDeepResearchSpinners,
        addErrorCard: mockAddErrorCard,
        completeDeepResearch: mockCompleteDeepResearch,
        setStreaming: mockSetStreaming,
        patchConversationMessage: mockPatchConversationMessage,
        addDeepResearchBanner: mockAddDeepResearchBanner,
      }
      return selector ? selector(state) : state
    }),
    {
      getState: vi.fn(() => mockStoreState),
      setState: vi.fn(),
    }
  ),
}))

vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({
    idToken: 'token-123',
  })),
}))

vi.mock('@/features/layout/store', () => ({
  useLayoutStore: vi.fn((selector?: (s: MockLayoutSelectorState) => unknown) => {
    const state: MockLayoutSelectorState = {
      openRightPanel: mockOpenRightPanel,
      setResearchPanelTab: mockSetResearchPanelTab,
    }
    return selector ? selector(state) : state
  }),
}))

describe('useLoadJobData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStoreState = {
      currentConversation: {
        id: 'conv-1',
        messages: createDefaultMessages(),
      },
      conversations: [],
      deepResearchJobId: null,
      deepResearchStreamLoaded: false,
      reportContent: '',
      isDeepResearchStreaming: false,
    }
  })

  test('loads report tab data through the report endpoint without replaying the full stream', async () => {
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-123', status: 'success', error: null })
    mockGetJobReport.mockResolvedValue({
      job_id: 'job-123',
      has_report: true,
      report: 'Loaded report',
    })
    mockGetJobState.mockResolvedValue({ job_id: 'job-123', has_state: false, artifacts: null })

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      await result.current.loadResearchPanelTab('job-123', 'report')
    })

    expect(mockSetResearchPanelTab).toHaveBeenCalledWith('report')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('research')
    expect(mockGetJobReport).toHaveBeenCalledWith('job-123', 'token-123')
    expect(mockSetReportContent).toHaveBeenCalledWith('Loaded report', 'final_report')
    expect(mockCreateDeepResearchClient).not.toHaveBeenCalled()
  })

  test('does not reload report tab data when the current job already has report content', async () => {
    mockStoreState.deepResearchJobId = 'job-123'
    mockStoreState.reportContent = 'Cached report'

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      await result.current.loadResearchPanelTab('job-123', 'report')
    })

    expect(mockSetResearchPanelTab).toHaveBeenCalledWith('report')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('research')
    expect(mockGetJobStatus).not.toHaveBeenCalled()
    expect(mockGetJobReport).not.toHaveBeenCalled()
    expect(mockCreateDeepResearchClient).not.toHaveBeenCalled()
  })

  test('loads thinking tab data by replaying the full stream', async () => {
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-123', status: 'success', error: null })
    mockCreateDeepResearchClient.mockImplementation(({ callbacks }) => ({
      connect: vi.fn(() => callbacks.onComplete?.()),
      disconnect: vi.fn(),
      isConnected: vi.fn(() => false),
      getLastEventId: vi.fn(() => null),
    }))

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      await result.current.loadResearchPanelTab('job-123', 'thinking')
    })

    expect(mockSetResearchPanelTab).toHaveBeenCalledWith('thinking')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('research')
    expect(mockGetJobReport).not.toHaveBeenCalled()
    expect(mockCreateDeepResearchClient).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: 'job-123',
        authToken: 'token-123',
      })
    )
  })

  test('marks unavailable completed report expired without surfacing a console error', async () => {
    mockGetJobStatus.mockRejectedValue(new Error('Failed to get job status: 404'))
    mockStoreState.currentConversation = {
      id: 'conv-1',
      messages: [
        {
          id: 'tracking-msg',
          role: 'assistant',
          content: 'Completed report',
          timestamp: new Date(),
          messageType: 'agent_response',
          deepResearchJobId: 'job-404',
          deepResearchJobStatus: 'success',
          showViewReport: true,
        },
        {
          id: 'success-banner',
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          messageType: 'deep_research_banner',
          deepResearchBannerData: { bannerType: 'success', jobId: 'job-404' },
        },
      ],
    }
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      await result.current.importJobStream('job-404')
    })

    expect(mockPatchConversationMessage).toHaveBeenCalledWith(
      'conv-1',
      'tracking-msg',
      expect.objectContaining({
        deepResearchJobStatus: 'failure',
        isDeepResearchActive: false,
        showViewReport: false,
        deepResearchReportExpired: true,
      })
    )
    expect(mockAddDeepResearchBanner).toHaveBeenCalledWith('expired', 'job-404', 'conv-1')
    expect(mockAddDeepResearchBanner).not.toHaveBeenCalledWith(
      'failure',
      expect.anything(),
      expect.anything()
    )
    expect(mockAddErrorCard).not.toHaveBeenCalled()
    expect(consoleErrorSpy).not.toHaveBeenCalled()
    consoleErrorSpy.mockRestore()
  })

  test('treats proxy failures as backend connectivity without expiring the report', async () => {
    mockGetJobStatus.mockRejectedValue(
      new Error('Failed to get job status: 500 - PROXY_ERROR: fetch failed')
    )
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      await result.current.importJobStream('job-404')
    })

    expect(mockPatchConversationMessage).not.toHaveBeenCalled()
    expect(mockAddDeepResearchBanner).not.toHaveBeenCalled()
    expect(mockStopAllDeepResearchSpinners).not.toHaveBeenCalled()
    expect(mockCompleteDeepResearch).not.toHaveBeenCalled()
    expect(mockSetStreaming).not.toHaveBeenCalled()
    expect(mockAddErrorCard).toHaveBeenCalledWith(
      'connection.failed',
      'The backend is not reachable. Start the backend and try again.',
      'Failed to get job status: 500 - PROXY_ERROR: fetch failed'
    )
    expect(consoleErrorSpy).not.toHaveBeenCalled()
    consoleErrorSpy.mockRestore()
  })

  test('does not commit full stream replay data after the user switches sessions', async () => {
    let streamCallbacks: {
      onOutputUpdate: (content: string, outputCategory?: string) => void
      onComplete: () => void
    } | null = null

    mockGetJobStatus.mockResolvedValue({ job_id: 'job-123', status: 'success', error: null })
    mockCreateDeepResearchClient.mockImplementation(({ callbacks }) => {
      streamCallbacks = callbacks
      return {
        connect: vi.fn(),
        disconnect: vi.fn(),
        isConnected: vi.fn(() => false),
        getLastEventId: vi.fn(() => null),
      }
    })

    mockStoreState.currentConversation = {
      id: 'conv-1',
      messages: [
        {
          id: 'tracking-msg',
          role: 'assistant',
          content: 'Completed report',
          timestamp: new Date(),
          messageType: 'agent_response',
          deepResearchJobId: 'job-123',
          deepResearchJobStatus: 'success',
          showViewReport: true,
        },
      ],
    }

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      const replay = result.current.importJobStream('job-123')
      await Promise.resolve()

      mockStoreState.currentConversation = {
        id: 'conv-2',
        messages: [],
      }
      expect(streamCallbacks).not.toBeNull()
      streamCallbacks!.onOutputUpdate('Report from the previous session', 'final_report')
      streamCallbacks!.onComplete()

      await replay
    })

    expect(useChatStore.setState).not.toHaveBeenCalled()
    expect(mockSetLoadedJobId).not.toHaveBeenCalled()
    expect(mockSetStreamLoaded).not.toHaveBeenCalled()
    expect(mockOpenRightPanel).not.toHaveBeenCalled()
  })

  test('does not promote uncategorized replay output into report content', async () => {
    let streamCallbacks: {
      onOutputUpdate: (content: string, outputCategory?: string) => void
      onJobStatus: (status: 'success' | 'failure' | 'interrupted', error?: string) => void
    } | null = null

    mockGetJobStatus.mockResolvedValue({ job_id: 'job-123', status: 'interrupted', error: null })
    mockCreateDeepResearchClient.mockImplementation(({ callbacks }) => {
      streamCallbacks = callbacks
      return {
        connect: vi.fn(),
        disconnect: vi.fn(),
        isConnected: vi.fn(() => false),
        getLastEventId: vi.fn(() => null),
      }
    })

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      const replay = result.current.importJobStream('job-123')
      await Promise.resolve()

      expect(streamCallbacks).not.toBeNull()
      streamCallbacks!.onOutputUpdate('{"status":"interrupted","reason":"cancelled"}')
      streamCallbacks!.onJobStatus('interrupted', 'cancelled by user')

      await replay
    })

    const replayCommit = vi.mocked(useChatStore.setState).mock.calls[0]?.[0]
    expect(replayCommit).toEqual(expect.any(Function))

    const updates = (replayCommit as (state: { currentStatus: string }) => object)({
      currentStatus: 'researching',
    })
    expect(updates).not.toHaveProperty('reportContent')
    expect(updates).not.toHaveProperty('reportContentCategory')
    expect(mockSetReportContent).not.toHaveBeenCalled()
  })

  test('imports root-level todos from full stream replay', async () => {
    let streamCallbacks: {
      onTodoUpdate: (todos: Array<{ id: string; content: string; status: 'pending' }>, workflow?: string) => void
      onComplete: () => void
    } | null = null

    mockGetJobStatus.mockResolvedValue({ job_id: 'job-123', status: 'success', error: null })
    mockCreateDeepResearchClient.mockImplementation(({ callbacks }) => {
      streamCallbacks = callbacks
      return {
        connect: vi.fn(),
        disconnect: vi.fn(),
        isConnected: vi.fn(() => false),
        getLastEventId: vi.fn(() => null),
      }
    })

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      const replay = result.current.importJobStream('job-123')
      await Promise.resolve()

      expect(streamCallbacks).not.toBeNull()
      streamCallbacks!.onTodoUpdate(
        [{ id: '1', content: 'Replay task', status: 'pending' }]
      )
      streamCallbacks!.onComplete()

      await replay
    })

    const replayCommit = vi.mocked(useChatStore.setState).mock.calls[0]?.[0]
    expect(replayCommit).toEqual(expect.any(Function))

    const updates = (replayCommit as unknown as (state: { currentStatus: string }) => Record<string, unknown>)({
      currentStatus: 'researching',
    })
    expect(updates.deepResearchTodos).toEqual([
      { id: 'todo-0-replay-task', content: 'Replay task', status: 'pending' },
    ])
  })

  test('does not import workflow-scoped sub-agent todos from full stream replay', async () => {
    let streamCallbacks: {
      onTodoUpdate: (todos: Array<{ id: string; content: string; status: 'pending' }>, workflow?: string) => void
      onComplete: () => void
    } | null = null

    mockGetJobStatus.mockResolvedValue({ job_id: 'job-123', status: 'success', error: null })
    mockCreateDeepResearchClient.mockImplementation(({ callbacks }) => {
      streamCallbacks = callbacks
      return {
        connect: vi.fn(),
        disconnect: vi.fn(),
        isConnected: vi.fn(() => false),
        getLastEventId: vi.fn(() => null),
      }
    })

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      const replay = result.current.importJobStream('job-123')
      await Promise.resolve()

      expect(streamCallbacks).not.toBeNull()
      streamCallbacks!.onTodoUpdate(
        [{ id: '1', content: 'Sub-agent task', status: 'pending' }],
        'researcher-agent'
      )
      streamCallbacks!.onComplete()

      await replay
    })

    const replayCommit = vi.mocked(useChatStore.setState).mock.calls[0]?.[0]
    expect(replayCommit).toEqual(expect.any(Function))

    const updates = (replayCommit as unknown as (state: { currentStatus: string }) => Record<string, unknown>)({
      currentStatus: 'researching',
    })
    expect(updates).not.toHaveProperty('deepResearchTodos')
  })
})
