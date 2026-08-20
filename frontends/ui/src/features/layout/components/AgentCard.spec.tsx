// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AgentCard, type AgentInfo } from './AgentCard'
import type { DeepResearchToolCall } from '@/features/chat/types'

const createToolCall = (overrides: Partial<DeepResearchToolCall> = {}): DeepResearchToolCall => ({
  id: 'tool-1',
  name: 'web_search_tool',
  status: 'complete',
  timestamp: new Date(),
  input: { query: 'test query' },
  ...overrides,
})

describe('AgentCard', () => {
  const createAgent = (overrides: Partial<AgentInfo> = {}): AgentInfo => ({
    id: 'agent-1',
    name: 'researcher-agent',
    status: 'running',
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('human labels', () => {
    test('renders the human agent title, never the raw id', () => {
      render(<AgentCard agent={createAgent({ name: 'planner-agent' })} />)

      expect(screen.getByText('Planning')).toBeInTheDocument()
      expect(screen.queryByText('planner-agent')).not.toBeInTheDocument()
    })

    test('renders the agent blurb', () => {
      render(<AgentCard agent={createAgent({ name: 'writer-agent' })} />)

      expect(screen.getByText('Writing the report')).toBeInTheDocument()
      expect(
        screen.getByText('Synthesizing findings into the final answer')
      ).toBeInTheDocument()
    })
  })

  describe('expand/collapse behavior', () => {
    test('shows current task by default when defaultExpanded is true', () => {
      render(<AgentCard agent={createAgent({ currentTask: 'Processing data...' })} />)

      expect(screen.getByText('Processing data...')).toBeInTheDocument()
    })

    test('shows tool calls (as human labels) by default when expanded', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', name: 'web_search_tool', input: { query: 'q1' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('Searching the web')).toBeInTheDocument()
      expect(screen.getByText('q1')).toBeInTheDocument()
    })

    test('is expandable EVEN while running', async () => {
      const user = userEvent.setup()

      render(
        <AgentCard
          agent={createAgent({ status: 'running', currentTask: 'Working...' })}
          defaultExpanded={false}
        />
      )

      const button = screen.getByRole('button')
      expect(button).not.toBeDisabled()
      expect(screen.queryByText('Working...')).not.toBeInTheDocument()

      await user.click(button)
      expect(screen.getByText('Working...')).toBeInTheDocument()
    })

    test('collapses when clicked (complete status)', async () => {
      const user = userEvent.setup()

      render(
        <AgentCard agent={createAgent({ status: 'complete', currentTask: 'Processing...' })} />
      )

      expect(screen.getByText('Processing...')).toBeInTheDocument()

      await user.click(screen.getByRole('button'))
      expect(screen.queryByText('Processing...')).not.toBeInTheDocument()
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

    test('an output-only completed agent stays expandable and shows its result', () => {
      render(
        <AgentCard
          agent={createAgent({
            status: 'complete',
            currentTask: undefined,
            toolCalls: [],
            output: 'Final synthesized result',
          })}
        />
      )

      expect(screen.getByRole('button')).not.toBeDisabled()
      expect(screen.getByText('Final synthesized result')).toBeInTheDocument()
    })
  })

  describe('tool call counts', () => {
    test('shows completed/total count in header', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', status: 'complete', input: { query: 'q1' } }),
              createToolCall({ id: 'tc-2', status: 'complete', input: { query: 'q2' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('2/2')).toBeInTheDocument()
    })

    test('reflects running tool calls in the count', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', status: 'complete', input: { query: 'q1' } }),
              createToolCall({ id: 'tc-2', status: 'running', input: { query: 'q2' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('1/2')).toBeInTheDocument()
    })
  })

  describe('tool call dedup', () => {
    test('keeps distinct calls with unrecognized inputs as separate rows', () => {
      render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', name: 'web_search_tool', input: undefined }),
              createToolCall({ id: 'tc-2', name: 'web_search_tool', input: undefined }),
            ],
          })}
        />
      )

      expect(screen.getByText('2/2')).toBeInTheDocument()
    })

    test('a terminal error replaces a prior running row for the same call', () => {
      const { container } = render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', status: 'running', input: { query: 'q1' } }),
              createToolCall({ id: 'tc-1', status: 'error', input: { query: 'q1' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('0/1')).toBeInTheDocument()
      expect(container.querySelector('.tool-call-row-dot .status-dot-error')).toBeTruthy()
      expect(container.querySelector('.tool-call-row-dot .status-dot-running')).toBeNull()
    })

    test('a retried complete replaces a prior error row for the same call', () => {
      const { container } = render(
        <AgentCard
          agent={createAgent({
            toolCalls: [
              createToolCall({ id: 'tc-1', status: 'error', input: { query: 'q1' } }),
              createToolCall({ id: 'tc-1', status: 'complete', input: { query: 'q1' } }),
            ],
          })}
        />
      )

      expect(screen.getByText('1/1')).toBeInTheDocument()
      expect(container.querySelector('.tool-call-row-dot .status-dot-error')).toBeNull()
    })
  })

  describe('accessibility', () => {
    test('button has aria-expanded attribute', async () => {
      const user = userEvent.setup()

      render(
        <AgentCard
          agent={createAgent({ status: 'complete', currentTask: 'Task content' })}
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
        <AgentCard agent={createAgent({ id: 'agent-123', currentTask: 'Task content' })} />
      )

      expect(screen.getByRole('button')).toHaveAttribute(
        'aria-controls',
        'agent-content-agent-123'
      )
    })

    test('omits disclosure ARIA when there is no expandable content', () => {
      render(
        <AgentCard
          agent={createAgent({
            status: 'complete',
            currentTask: undefined,
            output: undefined,
            toolCalls: [],
          })}
        />
      )

      const button = screen.getByRole('button')
      expect(button).toBeDisabled()
      expect(button).not.toHaveAttribute('aria-expanded')
      expect(button).not.toHaveAttribute('aria-controls')
    })
  })

  describe('defaultExpanded prop', () => {
    test('starts expanded when defaultExpanded is true', () => {
      render(<AgentCard agent={createAgent({ currentTask: 'Task content' })} defaultExpanded />)

      expect(screen.getByText('Task content')).toBeInTheDocument()
      expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true')
    })
  })
})
