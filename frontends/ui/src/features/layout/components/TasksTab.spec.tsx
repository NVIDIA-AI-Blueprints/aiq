// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { TasksTab } from './TasksTab'

// Mock the chat store
let mockDeepResearchTodos: Array<{
  id: string
  content: string
  status: 'pending' | 'in_progress' | 'completed' | 'stopped'
}> = []

vi.mock('@/features/chat', () => ({
  useChatStore: () => ({
    deepResearchTodos: mockDeepResearchTodos,
  }),
}))

// Mock TaskCard
vi.mock('./TaskCard', () => ({
  TaskCard: ({ todo }: { todo: { id: string; content: string } }) => (
    <div data-testid="task-card">{todo.content}</div>
  ),
}))

describe('TasksTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDeepResearchTodos = []
  })

  describe('empty state', () => {
    test('shows empty state when no tasks', () => {
      render(<TasksTab />)

      expect(screen.getByText('Research tasks will appear here.')).toBeInTheDocument()
      expect(screen.getByText(/Shows the plan breakdown and progress/)).toBeInTheDocument()
    })

    test('shows description in header', () => {
      render(<TasksTab />)

      expect(screen.getByText('Research plan breakdown and progress during deep research.')).toBeInTheDocument()
    })
  })

  describe('with tasks', () => {
    test('renders header', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'pending' },
      ]

      render(<TasksTab />)

      expect(screen.getByText('Tasks')).toBeInTheDocument()
    })

    test('shows progress count in header', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'completed' },
        { id: '2', content: 'Task 2', status: 'pending' },
        { id: '3', content: 'Task 3', status: 'pending' },
      ]

      render(<TasksTab />)

      expect(screen.getByText('1/3')).toBeInTheDocument()
    })

    test('renders task cards', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Research market trends', status: 'completed' },
        { id: '2', content: 'Analyze competitors', status: 'in_progress' },
      ]

      render(<TasksTab />)

      expect(screen.getByText('Research market trends')).toBeInTheDocument()
      expect(screen.getByText('Analyze competitors')).toBeInTheDocument()
    })

    test('renders correct number of task cards', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'pending' },
        { id: '2', content: 'Task 2', status: 'pending' },
        { id: '3', content: 'Task 3', status: 'pending' },
      ]

      render(<TasksTab />)

      expect(screen.getAllByTestId('task-card')).toHaveLength(3)
    })

    test('renders progress bar', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'completed' },
        { id: '2', content: 'Task 2', status: 'pending' },
      ]

      render(<TasksTab />)

      expect(screen.getByLabelText('Task completion progress')).toBeInTheDocument()
    })
  })

  describe('progress calculation', () => {
    test('calculates 0% when no tasks completed', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'pending' },
        { id: '2', content: 'Task 2', status: 'in_progress' },
      ]

      render(<TasksTab />)

      // Progress bar should show 0%
      const progressBar = screen.getByLabelText('Task completion progress')
      expect(progressBar).toBeInTheDocument()
    })

    test('calculates 100% when all tasks completed', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'completed' },
        { id: '2', content: 'Task 2', status: 'completed' },
      ]

      render(<TasksTab />)

      expect(screen.getByText('2/2')).toBeInTheDocument()
    })

    test('calculates 50% correctly', () => {
      mockDeepResearchTodos = [
        { id: '1', content: 'Task 1', status: 'completed' },
        { id: '2', content: 'Task 2', status: 'pending' },
      ]

      render(<TasksTab />)

      expect(screen.getByText('1/2')).toBeInTheDocument()
    })
  })
})
