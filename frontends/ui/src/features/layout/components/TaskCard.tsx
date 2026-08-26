// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TaskCard Component
 *
 * Row-like card displaying a single task/todo item with:
 * - KUI Checkbox (checked when complete, not clickable)
 * - Task name
 * - A shared StatusDot atom + a plain status word (In progress / Done / ...)
 *
 * SSE Events: artifact.update with type: "todo"
 */

'use client'

import { type FC } from 'react'
import { Flex, Text, Checkbox } from '@/adapters/ui'
import { StatusDot, todoStatusToNodeState } from '@/shared/components/research'
import type { DeepResearchTodo, DeepResearchTodoStatus } from '@/features/chat/types'

interface TaskCardProps {
  /** Todo item from deep research */
  todo: DeepResearchTodo
}

/** Plain status word shown next to the status atom. */
const getStatusText = (status: DeepResearchTodoStatus): string => {
  switch (status) {
    case 'completed':
      return 'Done'
    case 'in_progress':
      return 'In progress'
    case 'stopped':
      return 'Stopped'
    case 'pending':
    default:
      return 'Pending'
  }
}

/**
 * Card showing a single task's checkbox, name, and a status atom + plain word.
 */
export const TaskCard: FC<TaskCardProps> = ({ todo }) => {
  const isComplete = todo.status === 'completed'
  const statusText = getStatusText(todo.status)

  return (
    <Flex
      align="center"
      gap="3"
      className={`
        p-3 rounded-lg border border-base
        ${isComplete ? 'opacity-70' : ''}
      `}
    >
      {}
      <Checkbox checked={isComplete} disabled aria-label={`Task: ${todo.content}`} />

      {}
      <Text
        kind="label/semibold/md"
        className={`flex-1 min-w-0 ${isComplete ? 'line-through text-secondary' : 'text-primary'}`}
      >
        {todo.content}
      </Text>

      {}
      <Flex align="center" gap="2" className="shrink-0">
        <StatusDot state={todoStatusToNodeState(todo.status)} />
        <Text kind="body/regular/sm" className="text-secondary">
          {statusText}
        </Text>
      </Flex>
    </Flex>
  )
}
