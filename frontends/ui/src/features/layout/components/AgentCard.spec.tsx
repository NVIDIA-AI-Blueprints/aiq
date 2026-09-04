// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AgentCard, type AgentInfo } from './AgentCard'
import type { DeepResearchToolCall } from '@/features/chat/types'

const createToolCall = (overrides: Partial<DeepResearchToolCall> = {}): DeepResearchToolCall => ({
  id: 'tool-1',
  name: 'web_search',
  status: 'complete',
  timestamp: new Date(),
  input: { question: 'test query' },
  ...overrides,
})

describe('AgentCard', () => {
  const createAgent = (overrides: Partial<AgentInfo> = {}): AgentInfo => ({
    id: 'agent-1',
    name: 'test-agent',
    status: 'running',
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders agent name', () => {
      render(<AgentCard agent={createAgent({ name: 'planner-agent' })} />)

      expect(screen.getByText('planner-agent')).toBeInTheDocument()
    })

    test('renders with running status', () => {
      render(<AgentCard agent={createAgent({ status: 'running' })} />)

      expect(screen.getByLabelText('test-agent is running')).toBeInTheDocument()
    })

    test('renders with complete status', () => {
      render(<AgentCard agent={createAgent({ status: 'complete' })} />)

      expect(screen.queryByLabelText('test-agent is running')).not.toBeInTheDocument()
    })

    test('renders with error status', () => {
      render(<AgentCard agent={createAgent({ status: 'error' })} />)

      expect(screen.queryByLabelText('test-agent is running')).not.toBeInTheDocument()
    })

    test('renders with pending status', () => {
      render(<AgentCard agent={createAgent({ status: 'pending' })} />)

      expect(screen.queryByLabelText('test-agent is running')).not.toBeInTheDocument()
    })
  })

  describe('timestamp display', () => {
    test('shows completed timestamp when available', () => {
      const completedAt = new Date('2024-01-15T14:30:00')

      render(
        <AgentCard
          agent={createAgent({
            status: 'complete',
            completedAt,
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('shows started timestamp when no completed timestamp', () => {
      const startedAt = new Date('2024-01-15T14:00:00')

      render(
        <AgentCard
          agent={createAgent({
            status: 'pending',
            startedAt,
          })}
        />
      )

      expect(screen.getByText(/Started: \d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('handles ISO string timestamps', () => {
      render(
        <AgentCard
          agent={createAgent({
            status: 'complete',
            completedAt: '2024-01-15T14:30:00Z',
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })

  describe('expand/collapse behavior', () => {
    test('shows current task by default when defaultExpanded is true', () => {
      render(
        <AgentCard
          agent={createAgent({
            currentTask: 'Processing data...',
          })}
        />
      )

      expect(screen.getByText('Processing data...')).toBeInTheDocument()
    })

    test('shows tool calls by default when defaultExpanded is true', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', input: { question: 'search query 1' } }),
              createToolCall({ id: 'tc-2', input: { question: 'search query 2' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('search query 1')).toBeInTheDocument()
      expect(screen.getByText('search query 2')).toBeInTheDocument()
    })

    test('collapses when clicked (complete status)', async () => {
      const user = userEvent.setup()

      render(
        <AgentCard
          agent={createAgent({
            status: 'complete',
            currentTask: 'Processing...',
          })}
        />
      )

      expect(screen.getByText('Processing...')).toBeInTheDocument()

      await user.click(screen.getByRole('button'))
      expect(screen.queryByText('Processing...')).not.toBeInTheDocument()
    })

    test('button is disabled when running (cannot expand)', () => {
      render(
        <AgentCard
          agent={createAgent({
            status: 'running',
            currentTask: 'Processing...',
          })}
          defaultExpanded={false}
        />
      )

      expect(screen.getByRole('button')).toBeDisabled()
    })

    test('button is disabled when no expandable content', () => {
      render(
        <AgentCard
          agent={createAgent({
            currentTask: undefined,
            output: undefined,
            toolCalls: [],
          })}
        />
      )

      expect(screen.getByRole('button')).toBeDisabled()
    })
  })

  describe('tool call counts', () => {
    test('shows query count in header', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', input: { question: 'unique query 1' } }),
              createToolCall({ id: 'tc-2', input: { question: 'unique query 2' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('2/2 queries')).toBeInTheDocument()
    })

    test('shows running tool call count', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', status: 'complete', input: { question: 'completed query' } }),
              createToolCall({ id: 'tc-2', status: 'running', input: { question: 'running query' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('1/2 queries')).toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    test('button has aria-expanded attribute', async () => {
      const user = userEvent.setup()

      render(
        <AgentCard
          agent={createAgent({
            status: 'complete',
            currentTask: 'Task content',
          })}
          defaultExpanded={false}
        />
      )

      const button = screen.getByRole('button')
      expect(button).toHaveAttribute('aria-expanded', 'false')

      await user.click(button)
      expect(button).toHaveAttribute('aria-expanded', 'true')
    })

    test('button has aria-controls pointing to content', () => {
      render(
        <AgentCard
          agent={createAgent({
            id: 'agent-123',
            currentTask: 'Task content',
          })}
        />
      )

      expect(screen.getByRole('button')).toHaveAttribute(
        'aria-controls',
        'agent-content-agent-123'
      )
    })

    test('tool call checkboxes have aria-labels', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ input: { question: 'my search query' } }),
            ],
          })}
        />
      )

      expect(screen.getByLabelText('my search query')).toBeInTheDocument()
    })
  })

  describe('defaultExpanded prop', () => {
    test('starts expanded when defaultExpanded is true', () => {
      render(
        <AgentCard
          agent={createAgent({
            currentTask: 'Task content',
          })}
          defaultExpanded
        />
      )

      expect(screen.getByText('Task content')).toBeInTheDocument()
      expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true')
    })
  })
})
