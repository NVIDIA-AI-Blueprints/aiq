// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type {
  DeepResearchAgent,
  DeepResearchJobStatus,
  DeepResearchTodo,
} from '@/features/chat/types'
import { TasksTab } from './TasksTab'

interface MockStoreState {
  deepResearchTodos: DeepResearchTodo[]
  deepResearchAgents: DeepResearchAgent[]
  deepResearchStatus: DeepResearchJobStatus | null
  isDeepResearchStreaming: boolean
}

const createAgent = (
  name: string,
  status: DeepResearchAgent['status'],
  id = name
): DeepResearchAgent => ({
  id,
  name,
  status,
  startedAt: new Date('2026-01-01T00:00:00Z'),
  ...(status === 'complete' && { completedAt: new Date('2026-01-01T00:01:00Z') }),
})

let mockStoreState: MockStoreState

vi.mock('@/features/chat', () => ({
  useChatStore: (selector: (state: MockStoreState) => unknown) => selector(mockStoreState),
}))

vi.mock('./TaskCard', () => ({
  TaskCard: ({ todo }: { todo: DeepResearchTodo }) => (
    <div data-testid="task-card" data-status={todo.status}>
      {todo.content}
    </div>
  ),
}))

describe('TasksTab', () => {
  beforeEach(() => {
    mockStoreState = {
      deepResearchTodos: [],
      deepResearchAgents: [],
      deepResearchStatus: null,
      isDeepResearchStreaming: false,
    }
  })

  test('shows the legacy empty state for an inactive job without workflow traces', () => {
    render(<TasksTab />)

    expect(screen.getByText('Research tasks will appear here.')).toBeInTheDocument()
    expect(screen.getByText('Observed workflow progress during deep research.')).toBeInTheDocument()
    expect(screen.getByText('Shows each research phase after it begins.')).toBeInTheDocument()
  })

  test('shows lightweight starting activity before the first workflow begins', () => {
    mockStoreState.deepResearchStatus = 'submitted'
    mockStoreState.isDeepResearchStreaming = true

    render(<TasksTab />)

    expect(screen.getByText('Starting deep research…')).toBeInTheDocument()
    expect(screen.queryAllByTestId('task-card')).toHaveLength(0)
    expect(screen.queryByLabelText('Task completion progress')).not.toBeInTheDocument()
    expect(screen.queryByText('0/5')).not.toBeInTheDocument()
  })

  test('appends only an observed phase and ignores active model-generated todos', () => {
    mockStoreState.deepResearchTodos = [
      { id: 'legacy', content: 'Final synthesis only', status: 'in_progress' },
    ]
    mockStoreState.deepResearchAgents = [createAgent('source-router-agent', 'running')]
    mockStoreState.deepResearchStatus = 'running'
    mockStoreState.isDeepResearchStreaming = true

    render(<TasksTab />)

    expect(screen.getByText('Routing sources')).toHaveAttribute('data-status', 'in_progress')
    expect(screen.getAllByTestId('task-card')).toHaveLength(1)
    expect(screen.queryByText('Final synthesis only')).not.toBeInTheDocument()
    expect(screen.queryByText('Planning')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Task completion progress')).not.toBeInTheDocument()
  })

  test('shows between-phase activity without predicting the next phase', () => {
    mockStoreState.deepResearchAgents = [createAgent('source-router-agent', 'complete')]
    mockStoreState.deepResearchStatus = 'running'
    mockStoreState.isDeepResearchStreaming = true

    render(<TasksTab />)

    expect(screen.getByText('Routing sources')).toHaveAttribute('data-status', 'completed')
    expect(screen.getByText('Preparing next step…')).toBeInTheDocument()
    expect(screen.queryByText('Planning')).not.toBeInTheDocument()
  })

  test('does not fabricate planning or research when writing follows routing', () => {
    mockStoreState.deepResearchAgents = [
      createAgent('source-router-agent', 'complete'),
      createAgent('writer-agent', 'running'),
    ]
    mockStoreState.deepResearchStatus = 'running'
    mockStoreState.isDeepResearchStreaming = true

    render(<TasksTab />)

    expect(screen.getAllByTestId('task-card')).toHaveLength(2)
    expect(screen.getByText('Routing sources')).toHaveAttribute('data-status', 'completed')
    expect(screen.getByText('Writing the report')).toHaveAttribute('data-status', 'in_progress')
    expect(screen.queryByText('Planning')).not.toBeInTheDocument()
    expect(screen.queryByText(/Researching/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Writing final report/)).not.toBeInTheDocument()
  })

  test('aggregates parallel researcher executions into one observed row', () => {
    mockStoreState.deepResearchAgents = [
      createAgent('planner-agent', 'complete'),
      createAgent('researcher-agent', 'complete', 'researcher-1'),
      createAgent('researcher-agent', 'running', 'researcher-2'),
    ]
    mockStoreState.deepResearchStatus = 'running'
    mockStoreState.isDeepResearchStreaming = true

    render(<TasksTab />)

    expect(screen.getByText('Researching (1/2 researchers completed)')).toHaveAttribute(
      'data-status',
      'in_progress'
    )
    expect(screen.getAllByTestId('task-card')).toHaveLength(2)
  })

  test('shows finalizing activity only after every observed writer execution ends', () => {
    mockStoreState.deepResearchAgents = [createAgent('writer-agent', 'complete')]
    mockStoreState.deepResearchStatus = 'running'
    mockStoreState.isDeepResearchStreaming = true

    render(<TasksTab />)

    expect(screen.getByText('Writing the report')).toHaveAttribute('data-status', 'completed')
    expect(screen.getByText('Finalizing report…')).toBeInTheDocument()
  })

  test('stops a start-only phase when the restored job is terminal', () => {
    mockStoreState.deepResearchAgents = [createAgent('writer-agent', 'running')]
    mockStoreState.deepResearchStatus = 'success'

    render(<TasksTab />)

    expect(screen.getByText('Writing the report')).toHaveAttribute('data-status', 'stopped')
    expect(screen.queryByText('Finalizing report…')).not.toBeInTheDocument()
  })

  test('retains model-generated todo progress for an inactive legacy job', () => {
    mockStoreState.deepResearchTodos = [
      { id: 'legacy-1', content: 'Legacy research task', status: 'completed' },
      { id: 'legacy-2', content: 'Legacy writing task', status: 'pending' },
    ]

    render(<TasksTab />)

    expect(screen.getByText('Legacy research task')).toBeInTheDocument()
    expect(screen.getByText('Legacy writing task')).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getByLabelText('Task completion progress')).toBeInTheDocument()
  })

  test('shows only observed completed rows for a successful job', () => {
    mockStoreState.deepResearchAgents = [
      createAgent('source-router-agent', 'complete'),
      createAgent('writer-agent', 'complete'),
    ]
    mockStoreState.deepResearchStatus = 'success'

    render(<TasksTab />)

    expect(screen.getAllByTestId('task-card')).toHaveLength(2)
    expect(screen.queryByText('5/5')).not.toBeInTheDocument()
    expect(screen.queryByText('Finalizing report…')).not.toBeInTheDocument()
  })
})
