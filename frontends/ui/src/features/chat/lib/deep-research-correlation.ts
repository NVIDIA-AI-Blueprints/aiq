// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Deep research event correlation.
 *
 * Pairs deep-research workflow, tool, and LLM start/finish events using the
 * unique agent run id each event carries, so two workers that share a name
 * (several concurrent `researcher-agent` runs) are tracked as independent rows.
 * Extracted from the streaming callbacks so the correlation is exercised by
 * direct unit tests rather than only through the SSE hook.
 */

import type {
  DeepResearchAgent,
  DeepResearchLLMStep,
  DeepResearchToolCall,
  ThinkingStep,
} from '../types'

type NewThinkingStep = Omit<ThinkingStep, 'id' | 'timestamp' | 'userMessageId'>
type NewAgent = Omit<DeepResearchAgent, 'id' | 'startedAt' | 'status'>
type NewToolCall = Omit<DeepResearchToolCall, 'id' | 'timestamp' | 'status'>
type NewLLMStep = Omit<DeepResearchLLMStep, 'id' | 'timestamp' | 'isComplete'>
type LLMUsage = { input_tokens: number; output_tokens: number }

export interface ResearchCorrelatorDeps {
  hasUserMessage: () => boolean
  addThinkingStep: (step: NewThinkingStep) => string
  appendToThinkingStep: (stepId: string, content: string) => void
  completeThinkingStep: (stepId: string) => void
  addAgent: (agentId: string, agent: NewAgent) => string
  completeAgent: (agentId: string, output?: string) => void
  addToolCall: (toolCall: NewToolCall) => string
  completeToolCall: (toolCallId: string, output?: string) => void
  addLLMStep: (step: NewLLMStep) => string
  appendLLMStep: (stepId: string, chunk: string) => void
  completeLLMStep: (stepId: string, thinking?: string, usage?: LLMUsage) => void
}

export interface AdoptedRun {
  storeId: string
  thinkingStepId?: string
}

export interface ResearchCorrelator {
  onWorkflowStart: (agentId: string | undefined, name: string, input?: string) => void
  onWorkflowEnd: (agentId: string | undefined, name: string, output?: string) => void
  onLLMStart: (agentId: string | undefined, name: string, workflow?: string) => void
  onLLMChunk: (chunk: string) => void
  onLLMEnd: (
    agentId: string | undefined,
    name: string | undefined,
    thinking?: string,
    usage?: LLMUsage
  ) => void
  onToolStart: (
    agentId: string | undefined,
    name: string,
    input?: Record<string, unknown>,
    workflow?: string,
    isSandbox?: boolean
  ) => void
  onToolEnd: (agentId: string | undefined, name: string, output?: string) => void
  adoptAgent: (agentId: string, run: { thinkingStepId?: string }) => void
  adoptToolRun: (agentId: string | undefined, name: string, run: AdoptedRun) => void
  adoptLLMRun: (agentId: string | undefined, name: string, run: AdoptedRun) => void
  reset: () => void
}

interface RunEntry {
  key: string
  storeId: string
  thinkingStepId?: string
}

const ROOT_AGENT_KEY = '__root__'
const KEY_SEPARATOR = '\u0000'
const TOOL_OUTPUT_MAX = 500

export const createResearchCorrelator = (deps: ResearchCorrelatorDeps): ResearchCorrelator => {
  const agentSteps = new Map<string, { thinkingStepId?: string }>()
  const toolRuns = new Map<string, RunEntry[]>()
  const llmRuns = new Map<string, RunEntry[]>()
  const llmOrder: RunEntry[] = []

  const agentKeyOf = (agentId?: string): string => agentId || ROOT_AGENT_KEY
  const scopedKey = (agentId: string | undefined, name: string): string =>
    `${agentKeyOf(agentId)}${KEY_SEPARATOR}${name}`

  const pushRun = (map: Map<string, RunEntry[]>, entry: RunEntry): void => {
    const stack = map.get(entry.key)
    if (stack) stack.push(entry)
    else map.set(entry.key, [entry])
  }

  const popScoped = (map: Map<string, RunEntry[]>, key: string): RunEntry | undefined => {
    const stack = map.get(key)
    if (!stack || stack.length === 0) return undefined
    const entry = stack.pop()
    if (stack.length === 0) map.delete(key)
    return entry
  }

  const popByName = (map: Map<string, RunEntry[]>, name: string): RunEntry | undefined => {
    let latestKey: string | undefined
    for (const [key, stack] of map) {
      if (stack.length > 0 && key.endsWith(`${KEY_SEPARATOR}${name}`)) latestKey = key
    }
    return latestKey ? popScoped(map, latestKey) : undefined
  }

  const removeEntry = (map: Map<string, RunEntry[]>, entry: RunEntry): void => {
    const stack = map.get(entry.key)
    if (!stack) return
    const index = stack.lastIndexOf(entry)
    if (index >= 0) stack.splice(index, 1)
    if (stack.length === 0) map.delete(entry.key)
  }

  const removeFromOrder = (entry: RunEntry): void => {
    const index = llmOrder.lastIndexOf(entry)
    if (index >= 0) llmOrder.splice(index, 1)
  }

  const onWorkflowStart = (agentId: string | undefined, name: string, input?: string): void => {
    const key = agentKeyOf(agentId)
    let thinkingStepId: string | undefined
    if (deps.hasUserMessage()) {
      thinkingStepId = deps.addThinkingStep({
        category: 'agents',
        functionName: name,
        displayName: name,
        content: input ? `Input: ${input}\n` : 'Starting...\n',
        isComplete: false,
        isDeepResearch: true,
      })
    }
    deps.addAgent(key, { name, input })
    agentSteps.set(key, { thinkingStepId })
  }

  const onWorkflowEnd = (agentId: string | undefined, name: string, output?: string): void => {
    const key = agentKeyOf(agentId)
    const tracked = agentSteps.get(key)
    if (tracked?.thinkingStepId) {
      if (output) deps.appendToThinkingStep(tracked.thinkingStepId, `\nOutput: ${output}`)
      deps.completeThinkingStep(tracked.thinkingStepId)
    }
    agentSteps.delete(key)
    if (agentId) deps.completeAgent(agentId, output)
  }

  const onLLMStart = (agentId: string | undefined, name: string, workflow?: string): void => {
    let thinkingStepId: string | undefined
    if (deps.hasUserMessage()) {
      const displayName = workflow ? `${workflow} > ${name}` : name
      thinkingStepId = deps.addThinkingStep({
        category: 'agents',
        functionName: `llm:${name}`,
        displayName,
        content: 'Generating...\n',
        isComplete: false,
        isDeepResearch: true,
      })
    }
    const storeId = deps.addLLMStep({ name, workflow, content: '' })
    const entry: RunEntry = { key: scopedKey(agentId, name), storeId, thinkingStepId }
    pushRun(llmRuns, entry)
    llmOrder.push(entry)
  }

  const onLLMChunk = (chunk: string): void => {
    const entry = llmOrder[llmOrder.length - 1]
    if (!entry) return
    if (entry.thinkingStepId) deps.appendToThinkingStep(entry.thinkingStepId, chunk)
    deps.appendLLMStep(entry.storeId, chunk)
  }

  const onLLMEnd = (
    agentId: string | undefined,
    name: string | undefined,
    thinking?: string,
    usage?: LLMUsage
  ): void => {
    const entry =
      (name ? popScoped(llmRuns, scopedKey(agentId, name)) : undefined) ??
      (name ? popByName(llmRuns, name) : undefined) ??
      llmOrder[llmOrder.length - 1]
    if (!entry) return
    removeEntry(llmRuns, entry)
    removeFromOrder(entry)
    if (entry.thinkingStepId) {
      if (thinking) deps.appendToThinkingStep(entry.thinkingStepId, `\n\nThinking: ${thinking}`)
      deps.completeThinkingStep(entry.thinkingStepId)
    }
    deps.completeLLMStep(entry.storeId, thinking, usage)
  }

  const onToolStart = (
    agentId: string | undefined,
    name: string,
    input?: Record<string, unknown>,
    workflow?: string,
    isSandbox?: boolean
  ): void => {
    let thinkingStepId: string | undefined
    if (deps.hasUserMessage()) {
      const inputText = input
        ? '_raw' in input && typeof input._raw === 'string'
          ? input._raw
          : JSON.stringify(input, null, 2)
        : null
      thinkingStepId = deps.addThinkingStep({
        category: 'tools',
        functionName: name,
        displayName: name,
        content: inputText ? `Input: ${inputText}\n` : 'Executing...\n',
        isComplete: false,
        isDeepResearch: true,
      })
    }
    const storeId = deps.addToolCall({ name, input, workflow, agentId, isSandbox })
    pushRun(toolRuns, { key: scopedKey(agentId, name), storeId, thinkingStepId })
  }

  const onToolEnd = (agentId: string | undefined, name: string, output?: string): void => {
    const entry = popScoped(toolRuns, scopedKey(agentId, name)) ?? popByName(toolRuns, name)
    if (!entry) return
    if (entry.thinkingStepId) {
      if (output) {
        const truncated =
          output.length > TOOL_OUTPUT_MAX ? `${output.substring(0, TOOL_OUTPUT_MAX)}...` : output
        deps.appendToThinkingStep(entry.thinkingStepId, `\nOutput: ${truncated}`)
      }
      deps.completeThinkingStep(entry.thinkingStepId)
    }
    deps.completeToolCall(entry.storeId, output)
  }

  const adoptAgent = (agentId: string, run: { thinkingStepId?: string }): void => {
    agentSteps.set(agentKeyOf(agentId), { thinkingStepId: run.thinkingStepId })
  }

  const adoptToolRun = (
    agentId: string | undefined,
    name: string,
    run: AdoptedRun
  ): void => {
    pushRun(toolRuns, {
      key: scopedKey(agentId, name),
      storeId: run.storeId,
      thinkingStepId: run.thinkingStepId,
    })
  }

  const adoptLLMRun = (agentId: string | undefined, name: string, run: AdoptedRun): void => {
    const entry: RunEntry = {
      key: scopedKey(agentId, name),
      storeId: run.storeId,
      thinkingStepId: run.thinkingStepId,
    }
    pushRun(llmRuns, entry)
    llmOrder.push(entry)
  }

  const reset = (): void => {
    agentSteps.clear()
    toolRuns.clear()
    llmRuns.clear()
    llmOrder.length = 0
  }

  return {
    onWorkflowStart,
    onWorkflowEnd,
    onLLMStart,
    onLLMChunk,
    onLLMEnd,
    onToolStart,
    onToolEnd,
    adoptAgent,
    adoptToolRun,
    adoptLLMRun,
    reset,
  }
}
