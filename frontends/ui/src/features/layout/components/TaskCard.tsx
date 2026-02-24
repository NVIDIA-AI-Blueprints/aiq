// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TaskCard Component
 *
 * Row-like card displaying a single task/todo item with:
 * - KUI Checkbox (checked when complete, not clickable)
 * - Task name in label/semibold/md text
 * - Status badge with color based on status
 *
 * SSE Events: artifact.update with type: "todo"
 */

'use client'

import { type FC } from 'react'
import { Flex, Text, Checkbox, Badge } from '@/adapters/ui'
import { LoadingSpinner } from '@/adapters/ui/icons'
import type { DeepResearchTodo, DeepResearchTodoStatus } from '@/features/chat/types'

interface TaskCardProps {
  /** Todo item from deep research */
  todo: DeepResearchTodo
}

/**
 * Get badge color based on task status
 * - green: completed
 * - teal: in_progress
 * - yellow: pending
 * - red: stopped (error state)
 */
const getBadgeColor = (status: DeepResearchTodoStatus): 'green' | 'teal' | 'yellow' | 'red' => {
  switch (status) {
    case 'completed':
      return 'green'
    case 'in_progress':
      return 'teal'
    case 'pending':
      return 'yellow'
    case 'stopped':
      return 'red'
    default:
      return 'yellow'
  }
}

/**
 * Get display text for status badge
 */
const getStatusText = (status: DeepResearchTodoStatus): string => {
  switch (status) {
    case 'completed':
      return 'complete'
    case 'in_progress':
      return 'in progress'
    case 'pending':
      return 'pending'
    case 'stopped':
      return 'stopped'
    default:
      return status
  }
}

/**
 * Card showing a single task's checkbox, name, and status badge.
 */
export const TaskCard: FC<TaskCardProps> = ({ todo }) => {
  const isComplete = todo.status === 'completed'
  const badgeColor = getBadgeColor(todo.status)
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
      {/* Checkbox - checked when complete, always disabled (read-only) */}
      <Checkbox
        checked={isComplete}
        disabled
        aria-label={`Task: ${todo.content}`}
      />

      {/* Task Name */}
      <Text
        kind="label/semibold/md"
        className={`flex-1 min-w-0 ${isComplete ? 'line-through text-subtle' : 'text-primary'}`}
      >
        {todo.content}
      </Text>

      {/* Status Badge - with spinner for in_progress */}
      <Badge color={badgeColor}>
        <Flex align="center" gap="1">
          {todo.status === 'in_progress' && (
            <LoadingSpinner size="small" className="h-3 w-3" aria-label="In progress" />
          )}
          {statusText}
        </Flex>
      </Badge>
    </Flex>
  )
}
