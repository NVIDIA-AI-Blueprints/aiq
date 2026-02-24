// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect } from 'vitest'
import { ReportTab } from './ReportTab'

// Mock the chat store
vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn(() => ({
    reportContent: '',
    isStreaming: false,
    currentStatus: null,
  })),
}))

// Mock MarkdownRenderer
vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content, isStreaming }: { content: string; isStreaming?: boolean }) => (
    <div data-testid="markdown" data-streaming={isStreaming}>
      {content}
      {isStreaming && <span data-testid="streaming-indicator">Generating report...</span>}
    </div>
  ),
}))

// Mock ExportFooter
vi.mock('./ExportFooter', () => ({
  ExportFooter: () => <div data-testid="export-footer">Export Footer</div>,
}))

import { useChatStore } from '@/features/chat'

describe('ReportTab', () => {
  test('displays empty state when no report content', () => {
    render(<ReportTab />)

    expect(screen.getByText(/report content will appear here/i)).toBeInTheDocument()
    // Icon is rendered as SVG, verify by checking the document icon is present
    expect(document.querySelector('svg')).toBeInTheDocument()
  })

  test('renders report content via MarkdownRenderer', () => {
    vi.mocked(useChatStore).mockReturnValue({
      reportContent: '# Report Title\n\nReport content here',
      isStreaming: false,
      currentStatus: null,
    } as ReturnType<typeof useChatStore>)

    render(<ReportTab />)

    expect(screen.getByTestId('markdown')).toHaveTextContent('# Report Title')
  })

  test('renders title when provided', () => {
    vi.mocked(useChatStore).mockReturnValue({
      reportContent: 'Some content',
      isStreaming: false,
      currentStatus: null,
    } as ReturnType<typeof useChatStore>)

    render(<ReportTab />)

    expect(screen.getByText('Some content')).toBeInTheDocument()
  })

  test('shows generating indicator when streaming and writing', () => {
    vi.mocked(useChatStore).mockReturnValue({
      reportContent: 'Partial content...',
      isStreaming: true,
      currentStatus: 'writing',
    } as ReturnType<typeof useChatStore>)

    render(<ReportTab />)

    // Check that MarkdownRenderer receives isStreaming prop and shows indicator
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument()
    expect(screen.getByText('Generating report...')).toBeInTheDocument()
  })

  test('renders children when provided', () => {
    render(
      <ReportTab>
        <div>Custom content</div>
      </ReportTab>
    )

    expect(screen.getByText('Custom content')).toBeInTheDocument()
    expect(screen.queryByTestId('markdown')).not.toBeInTheDocument()
  })

  test('always renders export footer', () => {
    render(<ReportTab />)

    expect(screen.getByTestId('export-footer')).toBeInTheDocument()
  })
})
