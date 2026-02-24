// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AgentsTab } from './AgentsTab'
import { useChatStore } from '@/features/chat'
import type { AgentInfo } from './AgentCard'
import type { DeepResearchAgent, DeepResearchToolCall } from '@/features/chat/types'

vi.mock('./AgentCard', () => ({
  AgentCard: ({ agent }: { agent: AgentInfo }) => (
    <div data-testid="agent-card">
      {agent.name}
      {agent.toolCalls?.map((tc) => (
        <div key={tc.id} data-testid="tool-call">{tc.name}</div>
      ))}
    </div>
  ),
}))

const createStoreAgent = (overrides: Partial<DeepResearchAgent> = {}): DeepResearchAgent => ({
  id: 'agent-1',
  name: 'test-agent',
  status: 'running',
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
    vi.clearAllMocks()
    useChatStore.setState({
      deepResearchAgents: [],
      deepResearchToolCalls: [],
    })
  })

  describe('empty state', () => {
    test('shows empty state when no agents', () => {
      render(<AgentsTab />)

      expect(screen.getByText('Active agents will appear here during research.')).toBeInTheDocument()
      expect(screen.getByText(/Shows planner, researcher, and writer agents/)).toBeInTheDocument()
    })

    test('shows description in header', () => {
      render(<AgentsTab />)

      expect(screen.getByText('Active planner, researcher, and writer agents executing tasks.')).toBeInTheDocument()
    })
  })

  describe('with agents', () => {
    test('renders header', () => {
      useChatStore.setState({
        deepResearchAgents: [createStoreAgent()],
      })

      render(<AgentsTab />)

      expect(screen.getByText('Agents')).toBeInTheDocument()
    })

    test('renders agent cards', () => {
      useChatStore.setState({
        deepResearchAgents: [
          createStoreAgent({ id: '1', name: 'planner-agent' }),
          createStoreAgent({ id: '2', name: 'researcher-agent' }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('planner-agent')).toBeInTheDocument()
      expect(screen.getByText('researcher-agent')).toBeInTheDocument()
    })

    test('renders correct number of agent cards', () => {
      useChatStore.setState({
        deepResearchAgents: [
          createStoreAgent({ id: '1' }),
          createStoreAgent({ id: '2' }),
          createStoreAgent({ id: '3' }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getAllByTestId('agent-card')).toHaveLength(3)
    })

    test('groups tool calls by agent', () => {
      useChatStore.setState({
        deepResearchAgents: [
          createStoreAgent({ id: 'agent-1', name: 'researcher-agent' }),
        ],
        deepResearchToolCalls: [
          createToolCall({ id: 'tool-1', name: 'web_search', agentId: 'agent-1' }),
          createToolCall({ id: 'tool-2', name: 'tavily_search', agentId: 'agent-1' }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('researcher-agent')).toBeInTheDocument()
      expect(screen.getAllByTestId('tool-call')).toHaveLength(2)
    })

    test('ignores orphaned tool calls without agentId', () => {
      useChatStore.setState({
        deepResearchAgents: [
          createStoreAgent({ id: 'agent-1', name: 'researcher-agent' }),
        ],
        deepResearchToolCalls: [
          createToolCall({ id: 'tool-1', name: 'web_search', agentId: 'agent-1' }),
          createToolCall({ id: 'tool-2', name: 'write_todos', agentId: undefined }),
        ],
      })

      render(<AgentsTab />)

      expect(screen.getByText('researcher-agent')).toBeInTheDocument()
      expect(screen.getAllByTestId('tool-call')).toHaveLength(1)
    })
  })
})
