// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ExportFooter } from './ExportFooter'

// Mock busy state — controls what useIsCurrentSessionBusy returns
let mockIsBusy = false

// Mock the chat store and the centralized busy hook
let mockChatState: Record<string, unknown> = {
  reportContent: 'Some report content',
  isDeepResearchStreaming: false,
  deepResearchStatus: null as 'submitted' | 'running' | 'success' | 'failure' | 'interrupted' | null,
  currentConversation: { title: 'AI Market Trends' },
}

vi.mock('@/features/chat', () => ({
  useChatStore: (selector?: (state: any) => any) => {
    if (selector) {
      return selector(mockChatState)
    }
    return mockChatState
  },
  useIsCurrentSessionBusy: () => mockIsBusy,
}))

// Mock the download utilities
const mockDownloadAsMarkdown = vi.fn().mockReturnValue({ success: true })
vi.mock('@/utils/download-as-markdown', () => ({
  downloadAsMarkdown: (...args: unknown[]) => mockDownloadAsMarkdown(...args),
}))

const mockDownloadPdf = vi.fn()
vi.mock('@/hooks/use-download-pdf', () => ({
  useDownloadPdfRoute: () => ({
    downloadPdf: mockDownloadPdf,
    isLoading: false,
  }),
}))

describe('ExportFooter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('renders Markdown export button', () => {
    render(<ExportFooter />)

    expect(screen.getByRole('button', { name: /markdown/i })).toBeInTheDocument()
  })

  test('renders PDF export button', () => {
    render(<ExportFooter />)

    expect(screen.getByRole('button', { name: /pdf/i })).toBeInTheDocument()
  })

  test('calls downloadAsMarkdown with content and conversation title', async () => {
    const user = userEvent.setup()

    render(<ExportFooter />)

    await user.click(screen.getByRole('button', { name: /markdown/i }))

    expect(mockDownloadAsMarkdown).toHaveBeenCalledWith('Some report content', 'AI Market Trends')
  })

  test('calls downloadPdf with content and conversation title', async () => {
    const user = userEvent.setup()

    render(<ExportFooter />)

    await user.click(screen.getByRole('button', { name: /pdf/i }))

    expect(mockDownloadPdf).toHaveBeenCalledWith('Some report content', 'AI Market Trends')
  })

  test('disables buttons when disabled prop is true', () => {
    render(<ExportFooter disabled={true} />)

    expect(screen.getByRole('button', { name: /markdown/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /pdf/i })).toBeDisabled()
  })
})

describe('ExportFooter - Busy State (via useIsCurrentSessionBusy)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset mock state to default
    mockChatState = {
      reportContent: 'Some report content',
      isDeepResearchStreaming: false,
      deepResearchStatus: null,
      currentConversation: { title: 'AI Market Trends' },
    }
    mockIsBusy = false
  })

  test('disables buttons when session is busy (deep research streaming)', () => {
    mockIsBusy = true

    render(<ExportFooter />)

    expect(screen.getByRole('button', { name: /markdown/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /pdf/i })).toBeDisabled()
  })

  test('disables buttons when session is busy (submitted / running / HITL)', () => {
    mockIsBusy = true

    render(<ExportFooter />)

    expect(screen.getByRole('button', { name: /markdown/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /pdf/i })).toBeDisabled()
  })

  test('enables buttons when session is idle and research is complete', () => {
    mockIsBusy = false

    render(<ExportFooter />)

    expect(screen.getByRole('button', { name: /export as markdown/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /export as pdf/i })).not.toBeDisabled()
  })

  test('has appropriate title attribute when disabled due to active research', () => {
    mockIsBusy = true

    render(<ExportFooter />)

    const markdownButton = screen.getByRole('button', { name: /markdown/i })
    expect(markdownButton).toHaveAttribute('title', 'Export will be available when research is complete')
  })

  test('disables buttons when no content even if session is idle', () => {
    mockChatState.reportContent = ''
    mockIsBusy = false

    render(<ExportFooter />)

    expect(screen.getByRole('button', { name: /markdown/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /pdf/i })).toBeDisabled()
  })
})

