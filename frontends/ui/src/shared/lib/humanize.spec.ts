// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { ACRONYMS, titleCaseWords } from './humanize'

describe('titleCaseWords', () => {
  test('title-cases ordinary tokens', () => {
    expect(titleCaseWords('web_search_tool')).toBe('Web Search Tool')
    expect(titleCaseWords('knowledge_search')).toBe('Knowledge Search')
  })

  test('upper-cases known acronyms', () => {
    expect(titleCaseWords('api_gateway')).toBe('API Gateway')
    expect(titleCaseWords('sql_query')).toBe('SQL Query')
    expect(titleCaseWords('gpt_router')).toBe('GPT Router')
    for (const acronym of ACRONYMS) {
      expect(titleCaseWords(acronym)).toBe(acronym.toUpperCase())
    }
  })

  test('collapses repeated separators and whitespace, tolerates empty', () => {
    expect(titleCaseWords('api__gateway')).toBe('API Gateway')
    expect(titleCaseWords('web  search  tool')).toBe('Web Search Tool')
    expect(titleCaseWords('')).toBe('')
  })
})
