// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { useLoadJobData } from './use-load-job-data'
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
  deepResearchJobId: string | null
  deepResearchStreamLoaded: boolean
} = {
  currentConversation: {
    id: 'conv-1',
    messages: createDefaultMessages(),
  },
  deepResearchJobId: null as string | null,
  deepResearchStreamLoaded: false,
}

vi.mock('@/adapters/api', () => ({
  getJobStatus: (...args: unknown[]) => mockGetJobStatus(...args),
  getJobReport: (...args: unknown[]) => mockGetJobReport(...args),
  getJobState: (...args: unknown[]) => mockGetJobState(...args),
  createDeepResearchClient: (...args: unknown[]) => mockCreateDeepResearchClient(...args),
}))

vi.mock('../store', () => ({
  useChatStore: Object.assign(
    vi.fn((selector?: (s: any) => any) => {
      const state = {
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
    }
  ),
}))

vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({
    idToken: 'token-123',
  })),
}))

vi.mock('@/features/layout/store', () => ({
  useLayoutStore: vi.fn((selector?: (s: any) => any) => {
    const state = {
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
      deepResearchJobId: null,
      deepResearchStreamLoaded: false,
    }
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
    expect(mockAddDeepResearchBanner).not.toHaveBeenCalled()
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
})
