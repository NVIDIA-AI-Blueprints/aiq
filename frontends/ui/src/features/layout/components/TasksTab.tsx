// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TasksTab Component
 *
 * Tab within ResearchPanel showing task/todo items from DEEP RESEARCH only.
 * Displays the running todo list from artifact.update events with type: "todo".
 *
 * SSE Events: artifact.update with type: "todo"
 */

'use client'

import { type FC } from 'react'
import { Flex, Text, ProgressBar } from '@/adapters/ui'
import { CheckCircle } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { TaskCard } from './TaskCard'

/**
 * Tasks tab content showing todos/tasks from deep research.
 * Uses deepResearchTodos from the store (populated by SSE artifact.update events).
 */
export const TasksTab: FC = () => {
  const { deepResearchTodos, deepResearchJobId, currentStatus, isDeepResearchStreaming } = useChatStore()

  const isEmpty = deepResearchTodos.length === 0

  // Calculate progress stats
  const completedCount = deepResearchTodos.filter((t) => t.status === 'completed').length
  const totalCount = deepResearchTodos.length
  const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0
  const isWritingReport = isDeepResearchStreaming && currentStatus === 'writing'

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {/* Header with progress indicator */}
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-subtle">
            Tasks
          </Text>
          {deepResearchJobId && (
            <Text kind="body/regular/xs" className="text-tertiary">
              JobID: {deepResearchJobId}
            </Text>
          )}
          {totalCount > 0 && (
            <Text kind="body/regular/xs" className="text-subtle">
              {completedCount}/{totalCount}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/xs" className="text-subtle">
          Research plan breakdown and progress during deep research.
        </Text>
      </Flex>

      {/* Content */}
      {isEmpty ? (
        <Flex
          direction="col"
          align="center"
          justify="center"
          className="flex-1 text-center py-8"
        >
          <CheckCircle className="text-subtle mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-subtle">
            Research tasks will appear here.
          </Text>
          <Text kind="body/regular/sm" className="text-subtle mt-2">
            Shows the plan breakdown and progress during deep research.
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="3" className="flex-1 min-h-0 overflow-y-auto">
          {/* Progress bar showing completion percentage */}
          <div className="shrink-0">
            <ProgressBar value={progressPercent} aria-label="Task completion progress" />
          </div>

          {/* Writing report indicator */}
          {isWritingReport && (
            <Flex align="center" gap="2" className="shrink-0 rounded-md bg-blue-50 px-3 py-2 dark:bg-blue-950">
              <div className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
              <Text kind="body/regular/sm" className="text-blue-700 dark:text-blue-300">
                Writing final report... This may take a few minutes.
              </Text>
            </Flex>
          )}

          {/* Task list */}
          <Flex direction="col" gap="2">
            {deepResearchTodos.map((todo) => (
              <div key={todo.id} className="shrink-0">
                <TaskCard todo={todo} />
              </div>
            ))}
          </Flex>
        </Flex>
      )}
    </Flex>
  )
}
