// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import {
  formatModelName,
  getToolArgSummary,
  getToolLabel,
  isKnownTool,
  statusToNodeState,
  todoStatusToNodeState,
} from './research-labels'

describe('getToolLabel', () => {
  test('maps known tools to human labels and kinds', () => {
    expect(getToolLabel('web_search_tool')).toEqual({ label: 'Searching the web', kind: 'web' })
    expect(getToolLabel('advanced_web_search_tool')).toEqual({
      label: 'Searching the web (advanced)',
      kind: 'web',
    })
    expect(getToolLabel('paper_search_tool')).toEqual({ label: 'Searching papers', kind: 'doc' })
    expect(getToolLabel('knowledge_search')).toEqual({
      label: 'Searching the knowledge base',
      kind: 'doc',
    })
  })

  test('collapses a function-group prefix to the recognized tool', () => {
    expect(getToolLabel('search__web_search_tool').label).toBe('Searching the web')
  })

  test('strips angle brackets from internal wrapper names', () => {
    expect(getToolLabel('<workflow>').label).not.toContain('<')
    expect(getToolLabel('<workflow>').label).not.toContain('>')
  })

  test('renders agent nodes with their human agent title', () => {
    expect(getToolLabel('researcher').label).toBe('Researching')
    expect(getToolLabel('writer-agent').label).toBe('Writing the report')
    expect(getToolLabel('source-router-agent').label).toBe('Routing sources')
  })

  test('renders a model id as its last path segment in all caps', () => {
    expect(getToolLabel('azure/openai/gpt-5.2').label).toBe('GPT-5.2')
    expect(getToolLabel('gpt-oss-120b').label).toBe('GPT-OSS-120B')
    expect(getToolLabel('nemotron-3-super-120b-long-ctx').label).toBe(
      'NEMOTRON-3-SUPER-120B-LONG-CTX'
    )
  })
})

describe('formatModelName', () => {
  test('upper-cases the final path segment', () => {
    expect(formatModelName('azure/openai/gpt-5.2')).toBe('GPT-5.2')
    expect(formatModelName('gpt-oss-120b')).toBe('GPT-OSS-120B')
  })
})

describe('isKnownTool', () => {
  test('true for tools, false for agents and models', () => {
    expect(isKnownTool('web_search_tool')).toBe(true)
    expect(isKnownTool('knowledge_search')).toBe(true)
    expect(isKnownTool('researcher')).toBe(false)
    expect(isKnownTool('gpt-5.2')).toBe(false)
  })
})

describe('getToolArgSummary', () => {
  test('extracts the field value from a json payload string, not the raw dict', () => {
    expect(getToolArgSummary('web_search_tool', "```json {'query': 'Count the drivers'}```")).toBe(
      'Count the drivers'
    )
  })

  test('reads the query from a structured web-search input', () => {
    expect(getToolArgSummary('web_search_tool', { query: 'latest GPU roadmap' })).toBe(
      'latest GPU roadmap'
    )
  })

  test('reads the path from a structured file-op input', () => {
    expect(getToolArgSummary('write_file', { file_path: '/shared/x.json', content: 'big blob' })).toBe(
      '/shared/x.json'
    )
  })

  test('suppresses raw LLM message / prompt dumps', () => {
    expect(
      getToolArgSummary('intent_classifier', "```python messages=[HumanMessage(content='hi')]```")
    ).toBeUndefined()
    expect(getToolArgSummary('llm', "[SystemMessage(content='You are the orchestrator')]")).toBeUndefined()
  })

  test('returns undefined for a dict with no known field and for missing input', () => {
    expect(getToolArgSummary('x', "{'foo': 'bar'}")).toBeUndefined()
    expect(getToolArgSummary('x', undefined)).toBeUndefined()
  })
})

describe('status mappers', () => {
  test('statusToNodeState maps streaming statuses', () => {
    expect(statusToNodeState('complete')).toBe('done')
    expect(statusToNodeState('error')).toBe('error')
    expect(statusToNodeState('running')).toBe('running')
  })

  test('todoStatusToNodeState maps todo statuses', () => {
    expect(todoStatusToNodeState('in_progress')).toBe('running')
    expect(todoStatusToNodeState('completed')).toBe('done')
    expect(todoStatusToNodeState('stopped')).toBe('interrupted')
    expect(todoStatusToNodeState('pending')).toBe('pending')
  })
})
