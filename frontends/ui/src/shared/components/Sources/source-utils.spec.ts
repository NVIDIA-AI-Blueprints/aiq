// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { inferSourceKind, mapCitationSource, prettyDomain, sourceLabel } from './source-utils'

describe('inferSourceKind', () => {
  test('classifies web urls as web', () => {
    expect(inferSourceKind('https://nvidia.com/blog')).toBe('web')
    expect(inferSourceKind('http://docs.example.ai/x')).toBe('web')
  })
  test('classifies everything else as doc', () => {
    expect(inferSourceKind('knowledge_search')).toBe('doc')
    expect(inferSourceKind('fleet_overview.pdf')).toBe('doc')
    expect(inferSourceKind('mystery')).toBe('doc')
    expect(inferSourceKind(undefined)).toBe('doc')
  })
})

describe('prettyDomain', () => {
  test('strips protocol and www', () => {
    expect(prettyDomain('https://www.nvidia.com/path?q=1')).toBe('nvidia.com')
    expect(prettyDomain('http://docs.example.ai/x')).toBe('docs.example.ai')
  })
  test('degrades for non-urls', () => {
    expect(prettyDomain('knowledge_search')).toBe('knowledge_search')
    expect(prettyDomain(undefined)).toBe('')
  })
})

describe('sourceLabel', () => {
  test('domain for web, document label otherwise', () => {
    expect(sourceLabel('https://www.example.com', 'web')).toBe('example.com')
    expect(sourceLabel('knowledge_search', 'doc')).toBe('knowledge_search')
    expect(sourceLabel(undefined, 'doc')).toBe('Document')
  })
})

describe('mapCitationSource', () => {
  test('maps a web citation', () => {
    const ref = mapCitationSource({ id: 'c1', url: 'https://www.nvidia.com', content: 'NVIDIA news\nmore' }, 0)
    expect(ref).toMatchObject({ id: 'c1', kind: 'web', label: 'nvidia.com', title: 'NVIDIA news', url: 'https://www.nvidia.com' })
    expect(ref.snippet).toContain('NVIDIA news')
  })
  test('maps a document citation with no real url', () => {
    const ref = mapCitationSource({ id: 'c2', url: 'knowledge_search', content: 'There are 11,463 users.' }, 1)
    expect(ref.kind).toBe('doc')
    expect(ref.label).toBe('knowledge_search')
    expect(ref.url).toBeUndefined()
    expect(ref.title).toBe('There are 11,463 users.')
  })
  test('synthesises an id and title when missing', () => {
    const ref = mapCitationSource({ id: '', url: 'knowledge_search', content: '' }, 2)
    expect(ref.id).toBe('src-2')
    expect(ref.title).toBe('knowledge_search')
  })
})
