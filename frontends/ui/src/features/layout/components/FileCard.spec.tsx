// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { FileCard, type FileInfo } from './FileCard'

// Mock MarkdownRenderer
vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}))

describe('FileCard', () => {
  const createFile = (overrides: Partial<FileInfo> = {}): FileInfo => ({
    id: 'file-1',
    filename: 'report.md',
    content: 'File content here',
    timestamp: new Date('2024-01-15T14:30:00'),
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders filename', () => {
      render(<FileCard file={createFile({ filename: 'my-report.md' })} />)

      expect(screen.getByText('my-report.md')).toBeInTheDocument()
    })

    test('renders line count', () => {
      render(
        <FileCard
          file={createFile({
            content: 'Line 1\nLine 2\nLine 3',
          })}
        />
      )

      expect(screen.getByText('3 lines')).toBeInTheDocument()
    })

    test('renders timestamp when provided', () => {
      render(
        <FileCard
          file={createFile({ timestamp: new Date('2024-01-15T14:30:00') })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('does not render timestamp when not provided', () => {
      render(<FileCard file={createFile({ timestamp: undefined })} />)

      // Should not have extra timestamp text (only line count)
      const lineCount = screen.getByText(/lines/)
      expect(lineCount).toBeInTheDocument()
    })
  })

  describe('expand/collapse behavior', () => {
    test('shows preview when collapsed', () => {
      render(
        <FileCard
          file={createFile({ content: 'Short preview content' })}
        />
      )

      // Preview should be visible in collapsed state
      expect(screen.getByText('Short preview content')).toBeInTheDocument()
    })

    test('truncates long preview', () => {
      const longContent = 'A'.repeat(150)
      render(<FileCard file={createFile({ content: longContent })} />)

      // Should show truncated preview
      expect(screen.getByText(/\.\.\.$/)).toBeInTheDocument()
    })

    test('expands to show full content', async () => {
      const user = userEvent.setup()

      render(
        <FileCard
          file={createFile({
            filename: 'test.txt',
            content: 'Full content here',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByText('Content')).toBeInTheDocument()
      expect(screen.getByText('Full content here')).toBeInTheDocument()
    })

    test('collapses when clicked again', async () => {
      const user = userEvent.setup()

      render(<FileCard file={createFile()} />)

      // Expand
      await user.click(screen.getByRole('button'))
      expect(screen.getByText('Content')).toBeInTheDocument()

      // Collapse
      await user.click(screen.getByRole('button'))
      expect(screen.queryByText('Content')).not.toBeInTheDocument()
    })
  })

  describe('markdown rendering', () => {
    test('renders markdown files with MarkdownRenderer', async () => {
      const user = userEvent.setup()

      render(
        <FileCard
          file={createFile({
            filename: 'report.md',
            content: '# Heading\n\nParagraph',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByTestId('markdown')).toBeInTheDocument()
    })

    test('renders markdown for .markdown extension', async () => {
      const user = userEvent.setup()

      render(
        <FileCard
          file={createFile({
            filename: 'doc.markdown',
            content: '# Title',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByTestId('markdown')).toBeInTheDocument()
    })

    test('renders non-markdown files as preformatted text', async () => {
      const user = userEvent.setup()

      render(
        <FileCard
          file={createFile({
            filename: 'code.py',
            content: 'print("hello")',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      // Should render in a pre element, not MarkdownRenderer
      const preElement = screen.getByText('print("hello")').closest('pre')
      expect(preElement).toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    test('button has aria-expanded attribute', async () => {
      const user = userEvent.setup()

      render(<FileCard file={createFile()} />)

      const button = screen.getByRole('button')
      expect(button).toHaveAttribute('aria-expanded', 'false')

      await user.click(button)
      expect(button).toHaveAttribute('aria-expanded', 'true')
    })

    test('button has aria-controls pointing to content', () => {
      render(<FileCard file={createFile({ id: 'file-123' })} />)

      expect(screen.getByRole('button')).toHaveAttribute(
        'aria-controls',
        'file-content-file-123'
      )
    })
  })

  describe('empty content handling', () => {
    test('handles empty content gracefully', () => {
      render(<FileCard file={createFile({ content: '' })} />)

      // Should render without errors
      expect(screen.getByText('report.md')).toBeInTheDocument()
    })
  })

  describe('file extension detection', () => {
    test('detects .md as markdown', async () => {
      const user = userEvent.setup()

      render(
        <FileCard file={createFile({ filename: 'README.md', content: '# Test' })} />
      )

      await user.click(screen.getByRole('button'))
      expect(screen.getByTestId('markdown')).toBeInTheDocument()
    })

    test('treats files without extension as non-markdown', async () => {
      const user = userEvent.setup()

      render(
        <FileCard file={createFile({ filename: 'Dockerfile', content: 'FROM node' })} />
      )

      await user.click(screen.getByRole('button'))

      const preElement = screen.getByText('FROM node').closest('pre')
      expect(preElement).toBeInTheDocument()
    })
  })
})
