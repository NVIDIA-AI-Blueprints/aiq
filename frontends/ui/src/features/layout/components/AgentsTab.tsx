// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentsTab Component
 *
 * Sub-tab within ThinkingTab displaying active agents/workflows with their
 * tool calls shown as a checklist under each agent.
 *
 * SSE Events: workflow.start, workflow.end, tool.start, tool.end
 */

'use client'

import { type FC, useMemo } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { Wand } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { AgentCard, type AgentInfo } from './AgentCard'

/**
 * Agents sub-tab content showing active workflows with their tool calls.
 * Groups tool calls under their parent agents using agent_id.
 */
export const AgentsTab: FC = () => {
  const { deepResearchAgents, deepResearchToolCalls } = useChatStore()

  const agentsWithToolCalls = useMemo((): AgentInfo[] => {
    return deepResearchAgents.map((agent) => {
      const agentToolCalls = deepResearchToolCalls.filter((tc) => tc.agentId === agent.id)
      return {
        id: agent.id,
        name: agent.name,
        status: agent.status,
        currentTask: agent.input,
        startedAt: agent.startedAt,
        completedAt: agent.completedAt,
        output: agent.output,
        toolCalls: agentToolCalls,
      }
    })
  }, [deepResearchAgents, deepResearchToolCalls])

  const isEmpty = agentsWithToolCalls.length === 0
  const runningCount = agentsWithToolCalls.filter((a) => a.status === 'running').length
  const agentToolCalls = deepResearchToolCalls.filter((tc) => tc.agentId)
  const completedToolCalls = agentToolCalls.filter((tc) => tc.status === 'complete').length

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {/* Header */}
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-subtle">
            Agents
          </Text>
          {agentsWithToolCalls.length > 0 && (
            <Text kind="body/regular/xs" className="text-subtle">
              {runningCount > 0 ? `${runningCount} running` : `${agentsWithToolCalls.length}`}
              {agentToolCalls.length > 0 && ` • ${completedToolCalls}/${agentToolCalls.length} queries`}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/xs" className="text-subtle">
          Active planner, researcher, and writer agents executing tasks.
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
          <Wand className="text-subtle mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-subtle">
            Active agents will appear here during research.
          </Text>
          <Text kind="body/regular/sm" className="text-subtle mt-2">
            Shows planner, researcher, and writer agents as they execute.
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="2" className="flex-1 min-h-0 overflow-y-auto">
          {agentsWithToolCalls.map((agent) => (
            <div key={agent.id} className="shrink-0">
              <AgentCard agent={agent} defaultExpanded />
            </div>
          ))}
        </Flex>
      )}
    </Flex>
  )
}
