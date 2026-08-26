// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { TaskCard } from './TaskCard'
import type { DeepResearchTodo } from '@/features/chat/types'

describe('TaskCard', () => {
  const createTodo = (overrides: Partial<DeepResearchTodo> = {}): DeepResearchTodo => ({
    id: 'todo-1',
    content: 'Research market trends',
    status: 'pending',
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders task content', () => {
      render(<TaskCard todo={createTodo({ content: 'Analyze competitors' })} />)

      expect(screen.getByText('Analyze competitors')).toBeInTheDocument()
    })

    test('renders checkbox', () => {
      render(<TaskCard todo={createTodo()} />)

      expect(screen.getByRole('checkbox')).toBeInTheDocument()
    })

    test('checkbox is always disabled (read-only)', () => {
      render(<TaskCard todo={createTodo()} />)

      expect(screen.getByRole('checkbox')).toBeDisabled()
    })

    test('checkbox exists', () => {
      render(<TaskCard todo={createTodo({ content: 'My task' })} />)

      expect(screen.getByRole('checkbox')).toBeInTheDocument()
    })
  })

  describe('status word', () => {
    test('shows "Pending" for pending status', () => {
      render(<TaskCard todo={createTodo({ status: 'pending' })} />)

      expect(screen.getByText('Pending')).toBeInTheDocument()
    })

    test('shows "In progress" for in_progress status', () => {
      render(<TaskCard todo={createTodo({ status: 'in_progress' })} />)

      expect(screen.getByText('In progress')).toBeInTheDocument()
    })

    test('shows "Done" for completed status', () => {
      render(<TaskCard todo={createTodo({ status: 'completed' })} />)

      expect(screen.getByText('Done')).toBeInTheDocument()
    })

    test('shows "Stopped" for stopped status', () => {
      render(<TaskCard todo={createTodo({ status: 'stopped' })} />)

      expect(screen.getByText('Stopped')).toBeInTheDocument()
    })
  })

  describe('checkbox state', () => {
    test('checkbox is checked when task is completed', () => {
      render(<TaskCard todo={createTodo({ status: 'completed' })} />)

      expect(screen.getByRole('checkbox')).toBeChecked()
    })

    test('checkbox is unchecked when task is pending', () => {
      render(<TaskCard todo={createTodo({ status: 'pending' })} />)

      expect(screen.getByRole('checkbox')).not.toBeChecked()
    })

    test('checkbox is unchecked when task is in progress', () => {
      render(<TaskCard todo={createTodo({ status: 'in_progress' })} />)

      expect(screen.getByRole('checkbox')).not.toBeChecked()
    })

    test('checkbox is unchecked when task is stopped', () => {
      render(<TaskCard todo={createTodo({ status: 'stopped' })} />)

      expect(screen.getByRole('checkbox')).not.toBeChecked()
    })
  })

  describe('completed task styling', () => {
    test('completed tasks have reduced opacity', () => {
      render(<TaskCard todo={createTodo({ status: 'completed' })} />)

      const flexElements = screen.getAllByTestId('nv-flex')
      const hasOpacity = flexElements.some((el) => el.classList.contains('opacity-70'))
      expect(hasOpacity).toBe(true)
    })

    test('non-completed tasks do not have reduced opacity', () => {
      render(<TaskCard todo={createTodo({ status: 'pending' })} />)

      const flexElements = screen.getAllByTestId('nv-flex')
      const hasOpacity = flexElements.some((el) => el.classList.contains('opacity-70'))
      expect(hasOpacity).toBe(false)
    })

    test('completed task text has strikethrough', () => {
      render(<TaskCard todo={createTodo({ status: 'completed', content: 'Done task' })} />)

      const taskText = screen.getByText('Done task')
      expect(taskText).toHaveClass('line-through')
    })

    test('non-completed task text does not have strikethrough', () => {
      render(<TaskCard todo={createTodo({ status: 'pending', content: 'Pending task' })} />)

      const taskText = screen.getByText('Pending task')
      expect(taskText).not.toHaveClass('line-through')
    })
  })
})
