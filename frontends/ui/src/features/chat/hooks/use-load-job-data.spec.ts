// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { useLoadJobData } from './use-load-job-data'

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

let mockStoreState = {
  currentConversation: {
    id: 'conv-1',
    messages: [
      {
        id: 'tracking-msg',
        role: 'assistant' as const,
        content: '',
        timestamp: new Date(),
        messageType: 'agent_response' as const,
        deepResearchJobId: 'job-404',
        deepResearchJobStatus: 'running' as const,
        isDeepResearchActive: true,
      },
      {
        id: 'starting-banner',
        role: 'assistant' as const,
        content: '',
        timestamp: new Date(),
        messageType: 'deep_research_banner' as const,
        deepResearchBannerData: { bannerType: 'starting' as const, jobId: 'job-404' },
      },
    ],
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
    vi.fn(() => ({
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
    })),
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
  useLayoutStore: vi.fn(() => ({
    openRightPanel: mockOpenRightPanel,
    setResearchPanelTab: mockSetResearchPanelTab,
  })),
}))

describe('useLoadJobData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStoreState = {
      currentConversation: {
        id: 'conv-1',
        messages: [
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
        ],
      },
      deepResearchJobId: null,
      deepResearchStreamLoaded: false,
    }
  })

  test('marks unavailable job as failed when report load hits 404', async () => {
    mockGetJobStatus.mockRejectedValue(new Error('Failed to get job status: 404'))

    const { result } = renderHook(() => useLoadJobData())

    await act(async () => {
      await result.current.loadReport('job-404')
    })

    expect(mockPatchConversationMessage).toHaveBeenCalledWith(
      'conv-1',
      'tracking-msg',
      expect.objectContaining({
        deepResearchJobStatus: 'failure',
        isDeepResearchActive: false,
      })
    )
    expect(mockAddDeepResearchBanner).toHaveBeenCalledWith('failure', 'job-404', 'conv-1')
    expect(mockAddErrorCard).toHaveBeenCalledWith(
      'agent.deep_research_load_failed',
      'Failed to get job status: 404'
    )
  })
})
