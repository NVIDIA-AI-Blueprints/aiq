// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ThoughtTracesTab } from './ThoughtTracesTab'
import type { ThoughtInfo } from './ThoughtCard'

// Mock ThoughtCard
vi.mock('./ThoughtCard', () => ({
  ThoughtCard: ({ thought }: { thought: ThoughtInfo }) => (
    <div data-testid="thought-card">{thought.modelName}</div>
  ),
}))

describe('ThoughtTracesTab', () => {
  const createThought = (overrides: Partial<ThoughtInfo> = {}): ThoughtInfo => ({
    id: 'thought-1',
    modelName: 'gpt-4-turbo',
    content: 'Thinking about the problem...',
    isStreaming: false,
    timestamp: new Date(),
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('empty state', () => {
    test('shows empty state when no thought traces', () => {
      render(<ThoughtTracesTab thoughtTraces={[]} />)

      expect(screen.getByText('Thought traces will appear here during research.')).toBeInTheDocument()
      expect(screen.getByText(/Shows LLM chain-of-thought/)).toBeInTheDocument()
    })

    test('shows empty state when thoughtTraces prop is undefined', () => {
      render(<ThoughtTracesTab />)

      expect(screen.getByText('Thought traces will appear here during research.')).toBeInTheDocument()
    })
  })

  describe('with thought traces', () => {
    test('renders header', () => {
      render(<ThoughtTracesTab thoughtTraces={[createThought()]} />)

      expect(screen.getByText('Thought Traces')).toBeInTheDocument()
    })

    test('renders thought cards', () => {
      const thoughtTraces = [
        createThought({ id: '1', modelName: 'claude-3' }),
        createThought({ id: '2', modelName: 'gpt-4' }),
      ]

      render(<ThoughtTracesTab thoughtTraces={thoughtTraces} />)

      expect(screen.getByText('claude-3')).toBeInTheDocument()
      expect(screen.getByText('gpt-4')).toBeInTheDocument()
    })

    test('renders correct number of thought cards', () => {
      const thoughtTraces = [
        createThought({ id: '1' }),
        createThought({ id: '2' }),
        createThought({ id: '3' }),
      ]

      render(<ThoughtTracesTab thoughtTraces={thoughtTraces} />)

      expect(screen.getAllByTestId('thought-card')).toHaveLength(3)
    })
  })
})
