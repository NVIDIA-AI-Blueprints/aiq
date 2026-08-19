// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TasksTab Component
 *
 * Tab within ResearchPanel showing an append-only timeline of observed
 * deep-research workflows. Root todo artifacts support legacy jobs.
 */

'use client'

import { type FC, useMemo } from 'react'
import { Flex, Text, ProgressBar } from '@/adapters/ui'
import { useShallow } from 'zustand/react/shallow'
import { CheckCircle } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { deriveResearchProgress } from '@/features/chat/lib/deep-research-progress'
import { TaskCard } from './TaskCard'

/**
 * Tasks tab content showing compact workflow progress from deep research.
 */
export const TasksTab: FC = () => {
  const {
    deepResearchTodos,
    deepResearchAgents,
    deepResearchStatus,
    isDeepResearchStreaming,
  } = useChatStore(
    useShallow((s) => ({
      deepResearchTodos: s.deepResearchTodos,
      deepResearchAgents: s.deepResearchAgents,
      deepResearchStatus: s.deepResearchStatus,
      isDeepResearchStreaming: s.isDeepResearchStreaming,
    }))
  )

  const derivedProgress = useMemo(
    () => deriveResearchProgress(deepResearchAgents, deepResearchStatus, isDeepResearchStreaming),
    [deepResearchAgents, deepResearchStatus, isDeepResearchStreaming]
  )
  const usesLegacyTodos = derivedProgress === null
  const tasks = derivedProgress ?? deepResearchTodos

  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const totalCount = tasks.length
  const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

  const isTerminalJob =
    deepResearchStatus === 'success' ||
    deepResearchStatus === 'failure' ||
    deepResearchStatus === 'interrupted'
  const isWorkflowActive =
    !isTerminalJob &&
    (isDeepResearchStreaming ||
      deepResearchStatus === 'submitted' ||
      deepResearchStatus === 'running')
  const hasRunningPhase = tasks.some((task) => task.status === 'in_progress')
  const writers = deepResearchAgents.filter(
    (agent) => agent.name.trim().toLowerCase() === 'writer-agent'
  )
  const writerFinished =
    writers.length > 0 && writers.every((agent) => agent.status === 'complete')

  let workflowActivity: string | null = null
  if (!usesLegacyTodos && isWorkflowActive) {
    if (tasks.length === 0) workflowActivity = 'Starting deep research…'
    else if (!hasRunningPhase && writerFinished) workflowActivity = 'Finalizing report…'
    else if (!hasRunningPhase) workflowActivity = 'Preparing next step…'
  }

  const isEmpty = tasks.length === 0 && workflowActivity === null

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {}
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-primary">
            Tasks
          </Text>
          {usesLegacyTodos && totalCount > 0 && (
            <Text kind="body/regular/xs" className="text-secondary tabular-nums">
              {completedCount}/{totalCount}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/sm" className="text-secondary">
          Observed workflow progress during deep research.
        </Text>
      </Flex>

      {}
      {isEmpty ? (
        <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
          <CheckCircle className="text-secondary mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-secondary">
            Research tasks will appear here.
          </Text>
          <Text kind="body/regular/sm" className="text-secondary mt-2">
            Shows each research phase after it begins.
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="3" className="min-h-0 flex-1 overflow-y-auto">
          {}
          {usesLegacyTodos && totalCount > 0 && (
            <div className="shrink-0">
              <ProgressBar value={progressPercent} aria-label="Task completion progress" />
            </div>
          )}

          {}
          {workflowActivity && (
            <Flex align="center" gap="2" className="shrink-0 px-1 py-1">
              <div className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
              <Text kind="body/regular/sm" className="text-secondary">
                {workflowActivity}
              </Text>
            </Flex>
          )}

          {}
          <Flex direction="col" gap="2">
            {tasks.map((todo) => (
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
