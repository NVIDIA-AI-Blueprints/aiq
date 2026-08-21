// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import {
  EXPLANATION_FUNCTION_NAME,
  REASONING_FUNCTION_NAME,
  REFLECTION_FUNCTION_NAME,
  extractFoldedOutput,
  getDisplayName,
  isExplanationStep,
  isFoldedTextStep,
  isLLMModel,
  isReasoningStep,
  isReflectionStep,
  splitPayload,
} from './intermediate-step-parser'

describe('isLLMModel', () => {
  test.each([
    'azure/openai/gpt-5.2',
    'gpt-4.1-mini',
    'gpt-oss-120b',
    'claude-opus-4-8',
    'nemotron-3-ultra',
    'llm_call',
  ])('recognizes internal model trace %s', (name) => {
    expect(isLLMModel(name)).toBe(true)
  })

  test.each(['intent_classifier', 'shallow_research_agent', 'web_search_tool'])(
    'does not treat agent/tool %s as a model',
    (name) => {
      expect(isLLMModel(name)).toBe(false)
    }
  )

  test.each(['tool:web/search', ' Tool: web/search', 'function start: llm/call'])(
    'treats case- or whitespace-variant tool/function prefix %s as not a model',
    (name) => {
      expect(isLLMModel(name)).toBe(false)
    }
  )
})

describe('folded-text step predicates', () => {
  test('isReasoningStep matches only the reasoning sentinel', () => {
    expect(isReasoningStep(REASONING_FUNCTION_NAME)).toBe(true)
    expect(isReasoningStep('__reasoning__')).toBe(true)
    expect(isReasoningStep('__reflection__')).toBe(false)
  })

  test('isReflectionStep matches the sentinel and its unique-suffixed variants', () => {
    expect(isReflectionStep(REFLECTION_FUNCTION_NAME)).toBe(true)
    expect(isReflectionStep('__reflection__:ab12cd')).toBe(true)
    expect(isReflectionStep('__reasoning__')).toBe(false)
  })

  test('isExplanationStep matches only the explanation sentinel', () => {
    expect(isExplanationStep(EXPLANATION_FUNCTION_NAME)).toBe(true)
    expect(isExplanationStep('__explanation__')).toBe(true)
    expect(isExplanationStep('web_search_tool')).toBe(false)
  })

  test.each(['__reasoning__', '__reflection__', '__reflection__:aa11', '__explanation__'])(
    'isFoldedTextStep matches user-visible folded trace step %s',
    (name) => {
      expect(isFoldedTextStep(name)).toBe(true)
    }
  )

  test.each(['web_search_tool', 'intent_classifier', '<workflow>'])(
    'isFoldedTextStep does not classify tool/agent step %s as folded text',
    (name) => {
      expect(isFoldedTextStep(name)).toBe(false)
    }
  )
})

describe('getDisplayName', () => {
  test('upper-cases GPT in model names', () => {
    expect(getDisplayName('openai/gpt-5.6-sol')).toBe('GPT 5.6 Sol')
    expect(getDisplayName('openai/gpt-4.1-mini')).toBe('GPT 4.1 Mini')
  })

  test('preserves existing casing in model segments', () => {
    expect(getDisplayName('nvidia/nvidia/Nemotron-3-Nano-30B-A3B')).toBe('Nemotron 3 Nano 30B A3B')
  })

  test('maps known tools to human labels', () => {
    expect(getDisplayName('web_search_tool')).toBe('Searching the web')
  })

  test('title-cases unmapped function names', () => {
    expect(getDisplayName('intent_classifier')).toBe('Intent Classifier')
    expect(getDisplayName('<workflow>')).toBe('Workflow')
  })
})

describe('splitPayload', () => {
  test('splits input and output on the function markers', () => {
    const payload = '**Function Input:**\nplan the work\n**Function Output:**\ndone'
    expect(splitPayload(payload)).toEqual({ input: 'plan the work', output: 'done' })
  })

  test('treats a marker-less payload as all input', () => {
    expect(splitPayload('just some text')).toEqual({ input: 'just some text', output: '' })
  })

  test('returns empty halves for an empty payload', () => {
    expect(splitPayload('')).toEqual({ input: '', output: '' })
  })
})

describe('extractFoldedOutput', () => {
  test('keeps only the output half when markers are present', () => {
    expect(extractFoldedOutput('**Function Input:**\nq\n**Function Output:**\nthe note')).toBe(
      'the note'
    )
  })

  test('returns the trimmed content verbatim when there are no markers', () => {
    expect(extractFoldedOutput('  a plain note  ')).toBe('a plain note')
  })
})
