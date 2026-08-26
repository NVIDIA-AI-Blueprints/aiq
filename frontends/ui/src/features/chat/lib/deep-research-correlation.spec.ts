// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect } from 'vitest'
import { createResearchCorrelator, type ResearchCorrelatorDeps } from './deep-research-correlation'

interface Recorded {
  addThinkingStep: Array<{ id: string; step: Record<string, unknown> }>
  appendToThinkingStep: Array<[string, string]>
  completeThinkingStep: string[]
  addAgent: Array<{ id: string; agent: Record<string, unknown> }>
  completeAgent: Array<{ id: string; output?: string }>
  addToolCall: Array<{ id: string; toolCall: Record<string, unknown> }>
  completeToolCall: Array<{ id: string; output?: string }>
  addLLMStep: Array<{ id: string; step: Record<string, unknown> }>
  appendLLMStep: Array<[string, string]>
  completeLLMStep: Array<{ id: string; thinking?: string; usage?: unknown }>
}

const makeDeps = (hasUserMessage = true): { deps: ResearchCorrelatorDeps; calls: Recorded } => {
  const calls: Recorded = {
    addThinkingStep: [],
    appendToThinkingStep: [],
    completeThinkingStep: [],
    addAgent: [],
    completeAgent: [],
    addToolCall: [],
    completeToolCall: [],
    addLLMStep: [],
    appendLLMStep: [],
    completeLLMStep: [],
  }
  let stepN = 0
  let toolN = 0
  let llmN = 0
  const deps: ResearchCorrelatorDeps = {
    hasUserMessage: () => hasUserMessage,
    addThinkingStep: (step) => {
      const id = `step-${stepN++}`
      calls.addThinkingStep.push({ id, step: step as Record<string, unknown> })
      return id
    },
    appendToThinkingStep: (id, content) => calls.appendToThinkingStep.push([id, content]),
    completeThinkingStep: (id) => calls.completeThinkingStep.push(id),
    addAgent: (id, agent) => {
      calls.addAgent.push({ id, agent: agent as Record<string, unknown> })
      return id
    },
    completeAgent: (id, output) => calls.completeAgent.push({ id, output }),
    addToolCall: (toolCall) => {
      const id = `tool-${toolN++}`
      calls.addToolCall.push({ id, toolCall: toolCall as Record<string, unknown> })
      return id
    },
    completeToolCall: (id, output) => calls.completeToolCall.push({ id, output }),
    addLLMStep: (step) => {
      const id = `llm-${llmN++}`
      calls.addLLMStep.push({ id, step: step as Record<string, unknown> })
      return id
    },
    appendLLMStep: (id, chunk) => calls.appendLLMStep.push([id, chunk]),
    completeLLMStep: (id, thinking, usage) => calls.completeLLMStep.push({ id, thinking, usage }),
  }
  return { deps, calls }
}

describe('createResearchCorrelator', () => {
  describe('concurrent workers sharing a name', () => {
    test('two researcher-agent workers with distinct ids produce two independent rows', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onWorkflowStart('researcher-1', 'researcher-agent', 'query A')
      c.onWorkflowStart('researcher-2', 'researcher-agent', 'query B')

      expect(calls.addAgent.map((a) => a.id)).toEqual(['researcher-1', 'researcher-2'])
      expect(calls.addThinkingStep).toHaveLength(2)
      expect(calls.addThinkingStep[0].id).not.toBe(calls.addThinkingStep[1].id)
    })

    test('finishing worker A does not finish worker B or attach A output to B', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onWorkflowStart('researcher-1', 'researcher-agent', 'query A')
      c.onWorkflowStart('researcher-2', 'researcher-agent', 'query B')

      const stepA = calls.addThinkingStep[0].id
      const stepB = calls.addThinkingStep[1].id

      c.onWorkflowEnd('researcher-1', 'researcher-agent', 'output A')

      expect(calls.completeAgent).toEqual([{ id: 'researcher-1', output: 'output A' }])
      expect(calls.completeThinkingStep).toEqual([stepA])
      expect(calls.appendToThinkingStep).toContainEqual([stepA, '\nOutput: output A'])
      expect(calls.appendToThinkingStep).not.toContainEqual([stepB, '\nOutput: output A'])

      c.onWorkflowEnd('researcher-2', 'researcher-agent', 'output B')

      expect(calls.completeAgent).toEqual([
        { id: 'researcher-1', output: 'output A' },
        { id: 'researcher-2', output: 'output B' },
      ])
      expect(calls.completeThinkingStep).toEqual([stepA, stepB])
    })

    test('a worker with no matching finish stays running (never completed)', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onWorkflowStart('researcher-1', 'researcher-agent', 'query A')
      c.onWorkflowStart('researcher-2', 'researcher-agent', 'query B')
      const stepB = calls.addThinkingStep[1].id

      c.onWorkflowEnd('researcher-1', 'researcher-agent', 'output A')

      expect(calls.completeAgent).toEqual([{ id: 'researcher-1', output: 'output A' }])
      expect(calls.completeThinkingStep).not.toContain(stepB)
      expect(calls.completeAgent.map((a) => a.id)).not.toContain('researcher-2')
    })
  })

  describe('tool correlation', () => {
    test('scopes same-named tools to their owning worker by id', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onToolStart('researcher-1', 'web_search', { q: 'a' })
      c.onToolStart('researcher-2', 'web_search', { q: 'b' })
      const toolA = calls.addToolCall[0].id
      const toolB = calls.addToolCall[1].id

      c.onToolEnd('researcher-1', 'web_search', 'result A')
      expect(calls.completeToolCall).toEqual([{ id: toolA, output: 'result A' }])

      c.onToolEnd('researcher-2', 'web_search', 'result B')
      expect(calls.completeToolCall).toEqual([
        { id: toolA, output: 'result A' },
        { id: toolB, output: 'result B' },
      ])
    })

    test('passes agentId through to the tool call row', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onToolStart('researcher-1', 'web_search', { q: 'a' }, 'researcher-agent', false)
      expect(calls.addToolCall[0].toolCall).toMatchObject({
        name: 'web_search',
        input: { q: 'a' },
        workflow: 'researcher-agent',
        agentId: 'researcher-1',
      })
    })

    test('degrades to same-name match when the end event omits the agent id', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onToolStart('researcher-1', 'web_search', { q: 'a' })
      c.onToolEnd(undefined, 'web_search', 'result')

      expect(calls.completeToolCall).toEqual([{ id: calls.addToolCall[0].id, output: 'result' }])
    })
  })

  describe('LLM correlation', () => {
    test('concurrent same-named LLM runs complete against their own worker', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onLLMStart('researcher-1', 'gpt-4', 'researcher-agent')
      c.onLLMStart('researcher-2', 'gpt-4', 'researcher-agent')
      const llmA = calls.addLLMStep[0].id
      const llmB = calls.addLLMStep[1].id

      c.onLLMEnd('researcher-1', 'gpt-4', 'thinking A', { input_tokens: 1, output_tokens: 2 })
      expect(calls.completeLLMStep).toEqual([
        { id: llmA, thinking: 'thinking A', usage: { input_tokens: 1, output_tokens: 2 } },
      ])

      c.onLLMEnd('researcher-2', 'gpt-4', 'thinking B', { input_tokens: 3, output_tokens: 4 })
      expect(calls.completeLLMStep[1]).toEqual({
        id: llmB,
        thinking: 'thinking B',
        usage: { input_tokens: 3, output_tokens: 4 },
      })
    })

    test('chunks append to the most recently started open run', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onLLMStart('researcher-1', 'gpt-4')
      const llmA = calls.addLLMStep[0].id
      c.onLLMChunk('Hello ')
      expect(calls.appendLLMStep).toContainEqual([llmA, 'Hello '])
    })

    test('falls back to the open-run stack when the end event carries no id', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onLLMStart('researcher-1', 'gpt-4', 'researcher-agent')
      c.onLLMEnd(undefined, undefined, 'thinking', { input_tokens: 1, output_tokens: 2 })

      expect(calls.completeLLMStep).toEqual([
        { id: calls.addLLMStep[0].id, thinking: 'thinking', usage: { input_tokens: 1, output_tokens: 2 } },
      ])
    })
  })

  describe('replay adoption', () => {
    test('an adopted tool run completes on a later live end event', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.adoptToolRun(undefined, 'web_search', { storeId: 'tool-replay' })
      c.onToolEnd('researcher-1', 'web_search', 'result')

      expect(calls.completeToolCall).toEqual([{ id: 'tool-replay', output: 'result' }])
    })

    test('an adopted llm run completes on a later live end event', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.adoptLLMRun(undefined, 'gpt-4', { storeId: 'llm-replay' })
      c.onLLMEnd('researcher-1', 'gpt-4', 'thinking', { input_tokens: 1, output_tokens: 1 })

      expect(calls.completeLLMStep).toEqual([
        { id: 'llm-replay', thinking: 'thinking', usage: { input_tokens: 1, output_tokens: 1 } },
      ])
    })
  })

  describe('no active user message', () => {
    test('creates store rows but no thinking steps', () => {
      const { deps, calls } = makeDeps(false)
      const c = createResearchCorrelator(deps)

      c.onWorkflowStart('researcher-1', 'researcher-agent', 'query')
      c.onWorkflowEnd('researcher-1', 'researcher-agent', 'output')

      expect(calls.addThinkingStep).toHaveLength(0)
      expect(calls.completeThinkingStep).toHaveLength(0)
      expect(calls.addAgent).toEqual([{ id: 'researcher-1', agent: { name: 'researcher-agent', input: 'query' } }])
      expect(calls.completeAgent).toEqual([{ id: 'researcher-1', output: 'output' }])
    })
  })

  describe('reset', () => {
    test('drops tracked runs so later end events are ignored', () => {
      const { deps, calls } = makeDeps()
      const c = createResearchCorrelator(deps)

      c.onWorkflowStart('researcher-1', 'researcher-agent', 'query')
      c.reset()
      c.onWorkflowEnd('researcher-1', 'researcher-agent', 'output')

      expect(calls.completeThinkingStep).toHaveLength(0)
    })
  })
})
