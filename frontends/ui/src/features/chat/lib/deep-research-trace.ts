// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Deep Research trace adapter.
 *
 * Converts a completed (or replayed) deep-research run (agents and their tool
 * calls) into the same flat {@link ThinkingStep} stream the inline chat trace
 * renders. Each agent becomes a top-level phase; its tool calls nest under it
 * (carrying a short input summary); an explanation tool's output folds in as the
 * explanation block. Raw model reasoning is not surfaced here. Feeding the result
 * to ChatThinking gives the report's "thinking" tab the same phased trace (tool
 * labels, descriptions, durations) as the live run.
 */

import { getToolArgSummary } from '@/shared/components/research'
import { EXPLANATION_FUNCTION_NAME } from './intermediate-step-parser'
import type { DeepResearchAgent, DeepResearchToolCall, ThinkingStep } from '../types'

type RunStatus = 'running' | 'complete' | 'error'

const toStepStatus = (status: RunStatus): ThinkingStep['status'] =>
  status === 'error' ? 'error' : status === 'complete' ? 'success' : 'running'

const isExplanationTool = (name: string): boolean => /explain/i.test(name)

const ms = (value: Date | string): number => new Date(value).getTime()

const collapseRepeats = (steps: ThinkingStep[]): ThinkingStep[] => {
  const out: ThinkingStep[] = []
  const isFold = (step: ThinkingStep): boolean => step.category === 'agents' && !step.isTopLevel
  const sameCall = (a: ThinkingStep, b: ThinkingStep): boolean =>
    a.isTopLevel === b.isTopLevel &&
    a.functionName === b.functionName &&
    (a.argSummary ?? '') === (b.argSummary ?? '')
  const sameFold = (a: ThinkingStep, b: ThinkingStep): boolean =>
    a.functionName === b.functionName && a.content === b.content

  let lastToolIndex = -1
  for (const step of steps) {
    if (step.category === 'tools') {
      const lastTool = lastToolIndex >= 0 ? out[lastToolIndex] : undefined
      if (lastTool && sameCall(lastTool, step)) {
        out[lastToolIndex] = { ...step, id: lastTool.id }
      } else {
        out.push(step)
        lastToolIndex = out.length - 1
      }
      continue
    }
    if (isFold(step)) {
      const prev = out[out.length - 1]
      if (prev && isFold(prev) && sameFold(prev, step)) continue
      out.push(step)
      continue
    }
    out.push(step)
    lastToolIndex = -1
  }
  return out
}

const foldStep = (id: string, functionName: string, content: string): ThinkingStep => ({
  id,
  userMessageId: '',
  category: 'agents',
  functionName,
  displayName: functionName,
  content,
  timestamp: new Date(0),
  isComplete: true,
  isTopLevel: false,
  isDeepResearch: true,
})

const toolStep = (toolCall: DeepResearchToolCall, isTopLevel: boolean): ThinkingStep => ({
  id: toolCall.id,
  userMessageId: '',
  category: 'tools',
  functionName: toolCall.name,
  displayName: toolCall.name,
  content: toolCall.output ?? '',
  timestamp: toolCall.timestamp,
  isComplete: toolCall.status !== 'running',
  status: toStepStatus(toolCall.status),
  argSummary: getToolArgSummary(toolCall.name, toolCall.input),
  isTopLevel,
  isDeepResearch: true,
})

const withTool = (toolCall: DeepResearchToolCall, isTopLevel: boolean): ThinkingStep[] => {
  const out = [toolStep(toolCall, isTopLevel)]
  if (isExplanationTool(toolCall.name) && (toolCall.output ?? '').trim()) {
    out.push(
      foldStep(`${toolCall.id}__explanation`, EXPLANATION_FUNCTION_NAME, toolCall.output ?? '')
    )
  }
  return out
}

/**
 * Flatten a deep-research run into the {@link ThinkingStep} stream ChatThinking
 * folds into phases. Agents (in start order) are phase heads; their tool calls
 * nest under them; an explanation tool's output folds in as the explanation
 * block; tool calls with no owning agent trail as their own phases so nothing is
 * dropped. Raw model reasoning is not surfaced here (the deep panel shows what
 * the agent did, not its chain-of-thought).
 */
export const deepResearchToThinkingSteps = (
  agents: DeepResearchAgent[],
  toolCalls: DeepResearchToolCall[]
): ThinkingStep[] => {
  const steps: ThinkingStep[] = []
  const orderedAgents = [...agents].sort((a, b) => ms(a.startedAt) - ms(b.startedAt))
  const agentIds = new Set(agents.map((a) => a.id))

  for (const agent of orderedAgents) {
    const input = (agent.input ?? '').trim()
    steps.push({
      id: agent.id,
      userMessageId: '',
      category: 'agents',
      functionName: agent.name,
      displayName: agent.name,
      content: agent.output ?? '',
      timestamp: agent.startedAt,
      completedAt: agent.completedAt,
      isComplete: agent.status !== 'running',
      status: toStepStatus(agent.status),
      argSummary: getToolArgSummary(agent.name, input),
      isTopLevel: true,
      isDeepResearch: true,
    })

    toolCalls
      .filter((tc) => tc.agentId === agent.id)
      .sort((a, b) => ms(a.timestamp) - ms(b.timestamp))
      .forEach((tc) => steps.push(...withTool(tc, false)))
  }

  toolCalls
    .filter((tc) => !tc.agentId || !agentIds.has(tc.agentId))
    .sort((a, b) => ms(a.timestamp) - ms(b.timestamp))
    .forEach((tc) => steps.push(...withTool(tc, true)))

  return collapseRepeats(steps)
}
