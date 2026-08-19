// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type {
  DeepResearchAgent,
  DeepResearchJobStatus,
  DeepResearchTodo,
  DeepResearchTodoStatus,
} from '../types'
import { getAgentLabel } from '@/shared/components/research'

const PHASES = {
  routing: { id: 'phase:routing', agentName: 'source-router-agent' },
  planning: { id: 'phase:planning', agentName: 'planner-agent' },
  research: { id: 'phase:research', agentName: 'researcher-agent' },
  writing: { id: 'phase:writing', agentName: 'writer-agent' },
} as const

type PhaseKey = keyof typeof PHASES

const AGENT_PHASES: Record<string, PhaseKey> = {
  'source-router-agent': 'routing',
  'planner-agent': 'planning',
  researcher: 'research',
  'researcher-agent': 'research',
  'writer-agent': 'writing',
}

const isTerminalJob = (jobStatus: DeepResearchJobStatus | null): boolean =>
  jobStatus === 'success' || jobStatus === 'failure' || jobStatus === 'interrupted'

const isActiveJob = (jobStatus: DeepResearchJobStatus | null, isStreaming: boolean): boolean =>
  !isTerminalJob(jobStatus) &&
  (isStreaming || jobStatus === 'submitted' || jobStatus === 'running')

const getPhaseStatus = (
  agents: DeepResearchAgent[],
  terminal: boolean
): DeepResearchTodoStatus => {
  if (agents.every((agent) => agent.status === 'complete')) return 'completed'
  if (terminal || agents.some((agent) => agent.status === 'error')) return 'stopped'
  return 'in_progress'
}

/**
 * Project observed workflow lifecycle events into an append-only progress view.
 * Missing phases are never synthesized. Returns null only when an inactive job
 * has no recognized workflow trace, so callers can use legacy model todos.
 */
export const deriveResearchProgress = (
  agents: DeepResearchAgent[],
  jobStatus: DeepResearchJobStatus | null,
  isStreaming: boolean
): DeepResearchTodo[] | null => {
  const observedPhases = new Map<PhaseKey, DeepResearchAgent[]>()

  for (const agent of agents) {
    const phaseKey = AGENT_PHASES[agent.name.trim().toLowerCase()]
    if (!phaseKey) continue

    const phaseAgents = observedPhases.get(phaseKey)
    if (phaseAgents) phaseAgents.push(agent)
    else observedPhases.set(phaseKey, [agent])
  }

  if (observedPhases.size === 0) {
    return isActiveJob(jobStatus, isStreaming) ? [] : null
  }

  const terminal = isTerminalJob(jobStatus)
  return Array.from(observedPhases.entries()).map(([phaseKey, phaseAgents]) => {
    const phase = PHASES[phaseKey]
    let content = getAgentLabel(phase.agentName).title

    if (phaseKey === 'research') {
      const completed = phaseAgents.filter((agent) => agent.status === 'complete').length
      const noun = phaseAgents.length === 1 ? 'researcher' : 'researchers'
      content += ` (${completed}/${phaseAgents.length} ${noun} completed)`
    }

    return {
      id: phase.id,
      content,
      status: getPhaseStatus(phaseAgents, terminal),
    }
  })
}
