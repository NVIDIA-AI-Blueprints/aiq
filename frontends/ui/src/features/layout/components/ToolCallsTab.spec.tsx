// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ToolCallsTab } from './ToolCallsTab'
import type { ToolCallInfo } from './ToolCallCard'

// Mock ToolCallCard
vi.mock('./ToolCallCard', () => ({
  ToolCallCard: ({ toolCall }: { toolCall: ToolCallInfo }) => (
    <div data-testid="tool-call-card">{toolCall.name}</div>
  ),
}))

describe('ToolCallsTab', () => {
  const createToolCall = (overrides: Partial<ToolCallInfo> = {}): ToolCallInfo => ({
    id: 'tool-1',
    name: 'web_search',
    status: 'running',
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('empty state', () => {
    test('shows empty state when no tool calls', () => {
      render(<ToolCallsTab toolCalls={[]} />)

      expect(screen.getByText('Tool calls will appear here during research.')).toBeInTheDocument()
      expect(screen.getByText(/Shows web searches, file writes/)).toBeInTheDocument()
    })

    test('shows empty state when toolCalls prop is undefined', () => {
      render(<ToolCallsTab />)

      expect(screen.getByText('Tool calls will appear here during research.')).toBeInTheDocument()
    })

    test('shows wrench icon in empty state', () => {
      render(<ToolCallsTab toolCalls={[]} />)

      expect(screen.getByTestId('toolcalls-empty-icon')).toBeInTheDocument()
    })
  })

  describe('with tool calls', () => {
    test('renders header', () => {
      render(<ToolCallsTab toolCalls={[createToolCall()]} />)

      expect(screen.getByText('Tool Calls')).toBeInTheDocument()
    })

    test('renders tool call cards', () => {
      const toolCalls = [
        createToolCall({ id: '1', name: 'tavily_search' }),
        createToolCall({ id: '2', name: 'write_file' }),
      ]

      render(<ToolCallsTab toolCalls={toolCalls} />)

      expect(screen.getByText('tavily_search')).toBeInTheDocument()
      expect(screen.getByText('write_file')).toBeInTheDocument()
    })

    test('renders correct number of tool call cards', () => {
      const toolCalls = [
        createToolCall({ id: '1' }),
        createToolCall({ id: '2' }),
        createToolCall({ id: '3' }),
      ]

      render(<ToolCallsTab toolCalls={toolCalls} />)

      expect(screen.getAllByTestId('tool-call-card')).toHaveLength(3)
    })
  })
})
