// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { describe, test, expect, beforeEach } from 'vitest'
import { AgentsTab } from './AgentsTab'
import { useChatStore } from '@/features/chat'
import type { DeepResearchAgent, DeepResearchToolCall } from '@/features/chat/types'

const createStoreAgent = (overrides: Partial<DeepResearchAgent> = {}): DeepResearchAgent => ({
  id: 'agent-1',
  name: 'researcher',
  status: 'complete',
  startedAt: new Date(),
  ...overrides,
})

const createToolCall = (overrides: Partial<DeepResearchToolCall> = {}): DeepResearchToolCall => ({
  id: 'tool-1',
  name: 'web_search',
  status: 'complete',
  timestamp: new Date(),
  ...overrides,
})

describe('AgentsTab', () => {
  beforeEach(() => {
    useChatStore.setState({
      deepResearchAgents: [],
      deepResearchToolCalls: [],
      deepResearchLLMSteps: [],
    })
  })

  describe('empty state', () => {
    test('shows empty state when there are no steps', () => {
      render(<AgentsTab />)
      expect(
        screen.getByText('Research steps will appear here as the agent works.')
      ).toBeInTheDocument()
    })

    test('shows the description in the header', () => {
      render(<AgentsTab />)
      expect(screen.getByText('What the agent did, grouped by step.')).toBeInTheDocument()
    })
  })

  describe('with a completed run', () => {
    test('renders the Steps header', () => {
      useChatStore.setState({ deepResearchAgents: [createStoreAgent()] })
      render(<AgentsTab />)
      expect(screen.getByText('Steps')).toBeInTheDocument()
    })

    test('renders a data tool call in the trace (same trace as chat)', () => {
      useChatStore.setState({
        deepResearchAgents: [createStoreAgent({ id: 'a1', name: 'researcher' })],
        deepResearchToolCalls: [
          createToolCall({
            id: 't1',
            name: 'database_query',
            agentId: 'a1',
            input: { question: 'top customers by revenue' },
            output: 'Query (1 attempt(s)):\nSELECT customer_id FROM customers\n\nrows...',
          }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('top customers by revenue')).toBeInTheDocument()
    })

    test('counts orphan tool-call groups when there are no agents', () => {
      useChatStore.setState({
        deepResearchToolCalls: [
          createToolCall({ id: 't1', name: 'database_query', input: { question: 'count of orders' } }),
          createToolCall({ id: 't2', name: 'database_query', input: { question: 'top customers' } }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('2')).toBeInTheDocument()
    })

    test('counts a running orphan tool call toward the running header', () => {
      useChatStore.setState({
        deepResearchToolCalls: [
          createToolCall({
            id: 't1',
            name: 'database_query',
            status: 'running',
            input: { question: 'count of orders' },
          }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('1 running')).toBeInTheDocument()
    })

    test('renders a tool call with no owning agent', () => {
      useChatStore.setState({
        deepResearchToolCalls: [
          createToolCall({
            id: 't1',
            name: 'database_query',
            input: { question: 'count of orders' },
            output: 'Query (1 attempt(s)):\nSELECT count(*) FROM orders\n\n',
          }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('count of orders')).toBeInTheDocument()
    })
  })
})
