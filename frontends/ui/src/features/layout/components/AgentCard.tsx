// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentCard Component
 *
 * One authoritative agent row in the Steps view: a human title + blurb (never
 * the raw "planner-agent"), a single status atom, and a completed/total count.
 * Its tool calls nest underneath as uniform ToolCallRow entries. Expandable even
 * while the agent is still running.
 *
 * SSE Events:
 * - workflow.start: Creates or updates the row to "running"
 * - workflow.end: Updates the row to "complete"
 * - tool.start/end: Tool calls linked via agent_id
 */

'use client'

import { type FC, useState } from 'react'
import { Flex, Text, AnimatedChevron } from '@/adapters/ui'
import {
  StatusDot,
  ToolCallRow,
  getAgentLabel,
  getToolArgSummary,
  statusToNodeState,
} from '@/shared/components/research'
import type { DeepResearchToolCall } from '@/features/chat/types'

/** Agent/workflow information from SSE events */
export interface AgentInfo {
  /** Unique identifier for this agent instance */
  id: string
  /** Agent/workflow name (e.g., "planner-agent", "researcher-agent") */
  name: string
  /** Current execution status */
  status: 'pending' | 'running' | 'complete' | 'error'
  /** Description of current activity */
  currentTask?: string
  /** When agent started */
  startedAt?: Date | string
  /** When agent completed */
  completedAt?: Date | string
  /** Output from the agent (after completion) */
  output?: string
  /** Tool calls made by this agent */
  toolCalls?: DeepResearchToolCall[]
}

interface AgentCardProps {
  /** Agent information */
  agent: AgentInfo
  /** Whether to start expanded */
  defaultExpanded?: boolean
}

/** Map the agent's coarse status to the shared trace status atom. */
const agentNodeState = (status: AgentInfo['status']) => {
  if (status === 'pending') return 'pending' as const
  return statusToNodeState(status === 'complete' ? 'complete' : status === 'error' ? 'error' : 'running')
}

/**
 * Deduplicate tool calls by their argument summary (or name), keeping the latest
 * status so a re-run of the same query collapses to one row. `Map.set` on an
 * existing key updates the value while preserving its original iteration
 * position, so the row stays put and always reflects the most recent status.
 */
const dedupeToolCalls = (toolCalls: DeepResearchToolCall[]): DeepResearchToolCall[] => {
  const seen = new Map<string, DeepResearchToolCall>()
  for (const tc of toolCalls) {
    const summary = getToolArgSummary(tc.name, tc.input) ?? ''
    const key = summary ? `${tc.name}:${summary}` : `${tc.name}::${tc.id}`
    seen.set(key, tc)
  }
  return Array.from(seen.values())
}

/**
 * Expandable row showing a single agent's human label, status, and nested tool
 * calls. Expandable even while running so the user can watch work unfold.
 */
export const AgentCard: FC<AgentCardProps> = ({ agent, defaultExpanded = true }) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  const { title, blurb } = getAgentLabel(agent.name)
  const state = agentNodeState(agent.status)

  const toolCalls = dedupeToolCalls(agent.toolCalls || [])
  const completedToolCalls = toolCalls.filter((tc) => tc.status === 'complete').length
  const hasToolCalls = toolCalls.length > 0
  const output = agent.output?.trim()
  const hasExpandableContent = hasToolCalls || Boolean(agent.currentTask) || Boolean(output)
  const canExpand = hasExpandableContent

  return (
    <Flex
      direction="col"
      className="bg-surface-sunken border-base overflow-hidden rounded-lg border"
    >
      {}
      <button
        type="button"
        onClick={() => canExpand && setIsExpanded((v) => !v)}
        aria-expanded={canExpand ? isExpanded : undefined}
        aria-controls={canExpand ? `agent-content-${agent.id}` : undefined}
        className="flex w-full items-center gap-2 px-3 py-2 text-left disabled:cursor-default"
        disabled={!canExpand}
      >
        <span className="grid shrink-0 place-items-center">
          <StatusDot state={state} />
        </span>

        {}
        <Flex direction="col" gap="0" className="min-w-0 flex-1">
          <Flex align="center" gap="2">
            <Text kind="body/regular/sm" className="text-primary font-medium">
              {title}
            </Text>
            {hasToolCalls && (
              <Text kind="body/regular/xs" className="text-secondary tabular-nums">
                {completedToolCalls}/{toolCalls.length}
              </Text>
            )}
          </Flex>
          {blurb && (
            <Text kind="body/regular/xs" className="text-secondary truncate">
              {blurb}
            </Text>
          )}
        </Flex>

        {}
        {canExpand && (
          <span className="text-secondary shrink-0" aria-hidden="true">
            <AnimatedChevron state={isExpanded ? 'open' : 'closed'} />
          </span>
        )}
      </button>

      {}
      {isExpanded && hasExpandableContent && (
        <Flex
          id={`agent-content-${agent.id}`}
          direction="col"
          gap="2"
          className="border-base border-t px-3 pb-3 pt-2"
        >
          {agent.currentTask && (
            <div className="max-h-24 overflow-y-auto pr-1">
              <Text
                kind="body/regular/sm"
                className="text-secondary whitespace-pre-wrap break-words"
              >
                {agent.currentTask}
              </Text>
            </div>
          )}

          {output && (
            <div className="max-h-40 overflow-y-auto pr-1">
              <Text
                kind="body/regular/sm"
                className="text-secondary whitespace-pre-wrap break-words"
              >
                {output}
              </Text>
            </div>
          )}

          {hasToolCalls && (
            <Flex direction="col" gap="1.5">
              {toolCalls.map((toolCall) => (
                <ToolCallRow
                  key={toolCall.id}
                  name={toolCall.name}
                  status={statusToNodeState(toolCall.status)}
                  args={getToolArgSummary(toolCall.name, toolCall.input)}
                />
              ))}
            </Flex>
          )}
        </Flex>
      )}
    </Flex>
  )
}
