// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ThoughtCard, type ThoughtInfo } from './ThoughtCard'

// Mock MarkdownRenderer
vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}))

describe('ThoughtCard', () => {
  const createThought = (overrides: Partial<ThoughtInfo> = {}): ThoughtInfo => ({
    id: 'thought-1',
    modelName: 'gpt-4-turbo',
    content: 'Generated content',
    isStreaming: false,
    timestamp: new Date('2024-01-15T14:30:00'),
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders model name', () => {
      render(<ThoughtCard thought={createThought({ modelName: 'claude-3' })} />)

      expect(screen.getByText('claude-3')).toBeInTheDocument()
    })

    test('renders workflow name when provided', () => {
      render(
        <ThoughtCard
          thought={createThought({ workflow: 'researcher-agent' })}
        />
      )

      expect(screen.getByText('via researcher-agent')).toBeInTheDocument()
    })

    test('does not render workflow when not provided', () => {
      render(<ThoughtCard thought={createThought({ workflow: undefined })} />)

      expect(screen.queryByText(/via/)).not.toBeInTheDocument()
    })
  })

  describe('streaming state', () => {
    test('shows spinner when streaming', () => {
      render(<ThoughtCard thought={createThought({ isStreaming: true })} />)

      expect(screen.getByLabelText('Generating')).toBeInTheDocument()
    })

    test('shows timestamp when not streaming', () => {
      render(
        <ThoughtCard
          thought={createThought({
            isStreaming: false,
            timestamp: new Date('2024-01-15T14:30:00'),
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })

  describe('token usage', () => {
    test('shows token usage when not streaming', () => {
      render(
        <ThoughtCard
          thought={createThought({
            isStreaming: false,
            usage: { prompt_tokens: 100, completion_tokens: 50 },
          })}
        />
      )

      expect(screen.getByText('Tokens: 100 in / 50 out')).toBeInTheDocument()
    })

    test('does not show token usage when streaming', () => {
      render(
        <ThoughtCard
          thought={createThought({
            isStreaming: true,
            usage: { prompt_tokens: 100, completion_tokens: 50 },
          })}
        />
      )

      expect(screen.queryByText(/Tokens:/)).not.toBeInTheDocument()
    })

    test('does not show token usage when not provided', () => {
      render(<ThoughtCard thought={createThought({ usage: undefined })} />)

      expect(screen.queryByText(/Tokens:/)).not.toBeInTheDocument()
    })
  })

  describe('expand/collapse behavior', () => {
    test('shows preview when collapsed', () => {
      render(
        <ThoughtCard
          thought={createThought({ thinking: 'Thinking preview...' })}
        />
      )

      expect(screen.getByText('Thinking preview...')).toBeInTheDocument()
    })

    test('truncates long preview', () => {
      const longThinking = 'A'.repeat(150)
      render(<ThoughtCard thought={createThought({ thinking: longThinking })} />)

      expect(screen.getByText(/\.\.\.$/)).toBeInTheDocument()
    })

    test('expands to show thinking content', async () => {
      const user = userEvent.setup()

      render(
        <ThoughtCard
          thought={createThought({ thinking: 'Deep thinking here...' })}
        />
      )

      await user.click(screen.getByRole('button'))

      // Multiple markdown elements may be present (thinking + content)
      const markdownElements = screen.getAllByTestId('markdown')
      const hasThinkingContent = markdownElements.some((el) =>
        el.textContent?.includes('Deep thinking here...')
      )
      expect(hasThinkingContent).toBe(true)
    })

    test('expands to show output content', async () => {
      const user = userEvent.setup()

      render(
        <ThoughtCard
          thought={createThought({ content: 'Output content' })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByText('Output')).toBeInTheDocument()
      expect(screen.getByTestId('markdown')).toHaveTextContent('Output content')
    })

    test('collapses when clicked again', async () => {
      const user = userEvent.setup()

      render(<ThoughtCard thought={createThought({ content: 'Content' })} />)

      // Expand
      await user.click(screen.getByRole('button'))
      expect(screen.getByText('Output')).toBeInTheDocument()

      // Collapse
      await user.click(screen.getByRole('button'))
      expect(screen.queryByText('Output')).not.toBeInTheDocument()
    })
  })

  describe('preview priority', () => {
    test('prioritizes thinking content for preview', () => {
      render(
        <ThoughtCard
          thought={createThought({
            thinking: 'Thinking content',
            content: 'Output content',
          })}
        />
      )

      // Preview should show thinking, not output
      expect(screen.getByText('Thinking content')).toBeInTheDocument()
    })

    test('falls back to content when no thinking', () => {
      render(
        <ThoughtCard
          thought={createThought({
            thinking: undefined,
            content: 'Output content',
          })}
        />
      )

      expect(screen.getByText('Output content')).toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    test('button has aria-expanded attribute', async () => {
      const user = userEvent.setup()

      render(<ThoughtCard thought={createThought()} />)

      const button = screen.getByRole('button')
      expect(button).toHaveAttribute('aria-expanded', 'false')

      await user.click(button)
      expect(button).toHaveAttribute('aria-expanded', 'true')
    })

    test('button has aria-controls pointing to content', () => {
      render(<ThoughtCard thought={createThought({ id: 'thought-123' })} />)

      expect(screen.getByRole('button')).toHaveAttribute(
        'aria-controls',
        'thought-content-thought-123'
      )
    })
  })

  describe('timestamp handling', () => {
    test('handles Date object timestamp', () => {
      render(
        <ThoughtCard
          thought={createThought({
            isStreaming: false,
            timestamp: new Date('2024-01-15T14:30:00'),
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('handles ISO string timestamp', () => {
      render(
        <ThoughtCard
          thought={createThought({
            isStreaming: false,
            timestamp: '2024-01-15T14:30:00Z' as unknown as Date,
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })
})
