// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ToolCallCard, type ToolCallInfo } from './ToolCallCard'

describe('ToolCallCard', () => {
  const createToolCall = (overrides: Partial<ToolCallInfo> = {}): ToolCallInfo => ({
    id: 'tool-1',
    name: 'web_search',
    status: 'running',
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders tool name', () => {
      render(<ToolCallCard toolCall={createToolCall({ name: 'tavily_search' })} />)

      expect(screen.getByText('tavily_search')).toBeInTheDocument()
    })

    test('renders with running status and spinner', () => {
      render(<ToolCallCard toolCall={createToolCall({ status: 'running' })} />)

      expect(screen.getByLabelText('web_search is running')).toBeInTheDocument()
    })

    test('renders with complete status', () => {
      render(<ToolCallCard toolCall={createToolCall({ status: 'complete' })} />)

      expect(screen.queryByLabelText('web_search is running')).not.toBeInTheDocument()
    })

    test('renders with error status', () => {
      render(<ToolCallCard toolCall={createToolCall({ status: 'error' })} />)

      expect(screen.queryByLabelText('web_search is running')).not.toBeInTheDocument()
    })

    test('renders with pending status', () => {
      render(<ToolCallCard toolCall={createToolCall({ status: 'pending' })} />)

      expect(screen.queryByLabelText('web_search is running')).not.toBeInTheDocument()
    })
  })

  describe('workflow display', () => {
    test('shows parent workflow when provided', () => {
      render(
        <ToolCallCard
          toolCall={createToolCall({
            workflow: 'researcher-agent',
          })}
        />
      )

      expect(screen.getByText('via researcher-agent')).toBeInTheDocument()
    })

    test('does not show workflow when not provided', () => {
      render(<ToolCallCard toolCall={createToolCall({ workflow: undefined })} />)

      expect(screen.queryByText(/via/)).not.toBeInTheDocument()
    })
  })

  describe('timestamp display', () => {
    test('shows timestamp when available', () => {
      const timestamp = new Date('2024-01-15T14:30:00')

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'complete',
            timestamp,
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('handles ISO string timestamp', () => {
      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'complete',
            timestamp: '2024-01-15T14:30:00Z',
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('shows spinner instead of timestamp when running', () => {
      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'running',
            timestamp: new Date(),
          })}
        />
      )

      expect(screen.getByLabelText('web_search is running')).toBeInTheDocument()
    })
  })

  describe('expand/collapse behavior', () => {
    test('expands to show arguments when clicked', async () => {
      const user = userEvent.setup()

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'complete',
            arguments: { query: 'test search' },
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByText('Arguments')).toBeInTheDocument()
      expect(screen.getByText(/"query": "test search"/)).toBeInTheDocument()
    })

    test('expands to show result when clicked', async () => {
      const user = userEvent.setup()

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'complete',
            result: 'Search completed with 10 results',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByText('Result')).toBeInTheDocument()
      expect(screen.getByText('Search completed with 10 results')).toBeInTheDocument()
    })

    test('expands to show error when present', async () => {
      const user = userEvent.setup()

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'error',
            error: 'Rate limit exceeded',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByText('Error')).toBeInTheDocument()
      expect(screen.getByText('Rate limit exceeded')).toBeInTheDocument()
    })

    test('collapses when clicked again', async () => {
      const user = userEvent.setup()

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'complete',
            arguments: { query: 'test' },
          })}
        />
      )

      // Expand
      await user.click(screen.getByRole('button'))
      expect(screen.getByText('Arguments')).toBeInTheDocument()

      // Collapse
      await user.click(screen.getByRole('button'))
      expect(screen.queryByText('Arguments')).not.toBeInTheDocument()
    })
  })

  describe('preview text', () => {
    test('shows preview of arguments when collapsed', () => {
      render(
        <ToolCallCard
          toolCall={createToolCall({
            arguments: { query: 'short query' },
          })}
        />
      )

      expect(screen.getByText(/\{"query":"short query"\}/)).toBeInTheDocument()
    })

    test('truncates long argument preview', () => {
      const longArgs = { query: 'A'.repeat(150) }

      render(
        <ToolCallCard
          toolCall={createToolCall({
            arguments: longArgs,
          })}
        />
      )

      // Should show truncated JSON with ellipsis
      expect(screen.getByText(/\.\.\.$/)).toBeInTheDocument()
    })

    test('shows no preview when no arguments', () => {
      render(
        <ToolCallCard
          toolCall={createToolCall({
            arguments: undefined,
          })}
        />
      )

      // No preview text in collapsed state
      const button = screen.getByRole('button')
      expect(button.parentElement?.textContent).not.toContain('{')
    })
  })

  describe('accessibility', () => {
    test('button has aria-expanded attribute', async () => {
      const user = userEvent.setup()

      render(<ToolCallCard toolCall={createToolCall({ status: 'complete' })} />)

      const button = screen.getByRole('button')
      expect(button).toHaveAttribute('aria-expanded', 'false')

      await user.click(button)
      expect(button).toHaveAttribute('aria-expanded', 'true')
    })

    test('button has aria-controls pointing to content', () => {
      render(
        <ToolCallCard
          toolCall={createToolCall({
            id: 'tool-123',
          })}
        />
      )

      expect(screen.getByRole('button')).toHaveAttribute(
        'aria-controls',
        'tool-content-tool-123'
      )
    })
  })

  describe('shows all sections when all data present', () => {
    test('displays arguments, result, and error when expanded', async () => {
      const user = userEvent.setup()

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'error',
            arguments: { query: 'test' },
            result: 'Partial result',
            error: 'Timeout occurred',
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      expect(screen.getByText('Arguments')).toBeInTheDocument()
      expect(screen.getByText('Result')).toBeInTheDocument()
      expect(screen.getByText('Error')).toBeInTheDocument()
    })
  })

  describe('JSON formatting', () => {
    test('formats arguments JSON with proper indentation', async () => {
      const user = userEvent.setup()

      render(
        <ToolCallCard
          toolCall={createToolCall({
            status: 'complete',
            arguments: { query: 'test', limit: 10 },
          })}
        />
      )

      await user.click(screen.getByRole('button'))

      // Check for formatted JSON (multiple lines)
      const preElement = screen.getByText(/"query": "test"/).closest('pre')
      expect(preElement).toBeInTheDocument()
      expect(preElement?.textContent).toContain('\n')
    })
  })
})
