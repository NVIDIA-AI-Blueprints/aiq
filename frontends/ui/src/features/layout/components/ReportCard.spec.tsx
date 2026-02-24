// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ReportCard } from './ReportCard'

// Mock MarkdownRenderer
vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}))

// Mock download utilities
const mockDownloadAsMarkdown = vi.fn()
vi.mock('@/utils/download-as-markdown', () => ({
  downloadAsMarkdown: (...args: unknown[]) => mockDownloadAsMarkdown(...args),
}))

const mockDownloadPdf = vi.fn()
let mockIsPdfLoading = false

vi.mock('@/hooks/use-download-pdf', () => ({
  useDownloadPdfRoute: () => ({
    downloadPdf: mockDownloadPdf,
    isLoading: mockIsPdfLoading,
  }),
}))

// Mock the centralized busy hook (replaces ad-hoc store checks)
let mockIsBusy = false

vi.mock('@/features/chat', () => ({
  useIsCurrentSessionBusy: () => mockIsBusy,
}))

describe('ReportCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPdfLoading = false
    mockIsBusy = false
  })

  describe('empty state', () => {
    test('shows empty state when no content', () => {
      render(<ReportCard content="" />)

      expect(screen.getByText('The report will appear here once research is complete.')).toBeInTheDocument()
      expect(screen.getByText('You can export it as Markdown or PDF.')).toBeInTheDocument()
    })

    test('shows empty state for whitespace-only content', () => {
      render(<ReportCard content="   " />)

      expect(screen.getByText('The report will appear here once research is complete.')).toBeInTheDocument()
    })
  })

  describe('with content', () => {
    test('renders content via MarkdownRenderer', () => {
      render(<ReportCard content="# Report Title\n\nContent here" />)

      expect(screen.getByTestId('markdown')).toHaveTextContent('# Report Title')
    })

    test('displays word count', () => {
      render(<ReportCard content="One two three four five" />)

      expect(screen.getByText('5 words')).toBeInTheDocument()
    })

    test('displays title when provided', () => {
      render(<ReportCard content="Content" title="Market Analysis" />)

      expect(screen.getByText('Market Analysis')).toBeInTheDocument()
    })

    test('displays draft label when isDraft is true', () => {
      render(<ReportCard content="Content" isDraft={true} />)

      expect(screen.getByText('Draft')).toBeInTheDocument()
    })

    test('does not display draft label when isDraft is false', () => {
      render(<ReportCard content="Content" isDraft={false} />)

      expect(screen.queryByText('Draft')).not.toBeInTheDocument()
    })
  })

  describe('export buttons', () => {
    test('renders Markdown export button', () => {
      render(<ReportCard content="Content" />)

      expect(screen.getByRole('button', { name: 'Export as Markdown' })).toBeInTheDocument()
    })

    test('renders PDF export button', () => {
      render(<ReportCard content="Content" />)

      expect(screen.getByRole('button', { name: 'Export as PDF' })).toBeInTheDocument()
    })

    test('calls downloadAsMarkdown when Markdown button clicked', async () => {
      const user = userEvent.setup()

      render(<ReportCard content="Report content" />)

      await user.click(screen.getByRole('button', { name: 'Export as Markdown' }))

      expect(mockDownloadAsMarkdown).toHaveBeenCalledWith('Report content')
    })

    test('calls downloadPdf when PDF button clicked', async () => {
      const user = userEvent.setup()

      render(<ReportCard content="Report content" />)

      await user.click(screen.getByRole('button', { name: 'Export as PDF' }))

      expect(mockDownloadPdf).toHaveBeenCalledWith('Report content')
    })
  })

  describe('disabled states', () => {
    test('export buttons disabled when session is busy', () => {
      mockIsBusy = true

      render(<ReportCard content="Content" />)

      expect(screen.getByRole('button', { name: /Export as Markdown/ })).toBeDisabled()
      expect(screen.getByRole('button', { name: /Export as PDF/ })).toBeDisabled()
    })

    test('PDF button disabled when loading', () => {
      mockIsPdfLoading = true

      render(<ReportCard content="Content" />)

      expect(screen.getByRole('button', { name: /Generating PDF/ })).toBeDisabled()
    })

    test('shows "Generating..." when PDF is loading', () => {
      mockIsPdfLoading = true

      render(<ReportCard content="Content" />)

      expect(screen.getByText('Generating...')).toBeInTheDocument()
    })

    test('does not call export when buttons are disabled', async () => {
      const user = userEvent.setup()
      mockIsBusy = true

      render(<ReportCard content="Content" />)

      await user.click(screen.getByRole('button', { name: /Export as Markdown/ }))
      await user.click(screen.getByRole('button', { name: /Export as PDF/ }))

      expect(mockDownloadAsMarkdown).not.toHaveBeenCalled()
      expect(mockDownloadPdf).not.toHaveBeenCalled()
    })
  })

  describe('word count calculation', () => {
    test('counts words correctly', () => {
      render(<ReportCard content="This is a test report with several words" />)

      expect(screen.getByText('8 words')).toBeInTheDocument()
    })

    test('handles multiple spaces between words', () => {
      render(<ReportCard content="One   two    three" />)

      expect(screen.getByText('3 words')).toBeInTheDocument()
    })

    test('handles newlines in content', () => {
      render(<ReportCard content={`Line one
Line two
Line three`} />)

      expect(screen.getByText('6 words')).toBeInTheDocument()
    })

    test('formats large word counts with commas', () => {
      const longContent = 'word '.repeat(1500)

      render(<ReportCard content={longContent} />)

      expect(screen.getByText('1,500 words')).toBeInTheDocument()
    })
  })
})
