// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { getDataSourceDisplay, getDataSourceKind, getDataSourceLabel } from './data-sources'

describe('getDataSourceLabel', () => {
  test('returns a known base label', () => {
    expect(getDataSourceLabel('web_search')).toBe('Web Search')
    expect(getDataSourceLabel('gdrive')).toBe('Google Drive')
  })

  test('title-cases an unknown id', () => {
    expect(getDataSourceLabel('custom_source')).toBe('Custom Source')
  })
})

describe('getDataSourceDisplay', () => {
  test('returns the source name and description unchanged when no override exists', () => {
    expect(getDataSourceDisplay({ id: 'confluence', name: 'Confluence', description: 'Docs' })).toEqual({
      name: 'Confluence',
      description: 'Docs',
    })
  })

  test('coerces a null description to an empty string', () => {
    expect(getDataSourceDisplay({ id: 'x', name: 'X', description: null })).toEqual({
      name: 'X',
      description: '',
    })
  })
})

describe('getDataSourceKind', () => {
  test('maps web/search sources to the web kind', () => {
    expect(getDataSourceKind('web_search')).toBe('web')
    expect(getDataSourceKind('glean')).toBe('web')
  })

  test('maps everything else to the doc kind', () => {
    expect(getDataSourceKind('confluence')).toBe('doc')
    expect(getDataSourceKind('people')).toBe('doc')
  })
})
