// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { MAX_CATEGORY_BARS, degenerateKpis, normalizeChart } from './normalize'
import type { ChartSpec } from './types'

function spec(overrides: Partial<ChartSpec>): ChartSpec {
  return {
    type: 'bar',
    title: 'T',
    x: { key: 'cat' },
    series: [{ key: 'v' }],
    data: [
      { cat: 'a', v: 10 },
      { cat: 'b', v: 20 },
    ],
    ...overrides,
  } as ChartSpec
}

describe('degenerateKpis', () => {
  test('multi-series charts are never degenerate', () => {
    expect(degenerateKpis(spec({ series: [{ key: 'v' }, { key: 'w' }] }))).toBeNull()
  })

  test('a single plottable value uses the dominant row', () => {
    const kpis = degenerateKpis(spec({ data: [{ cat: 'only', v: 42 }] }))
    expect(kpis).toEqual([{ label: 'T', value: '42', sub: 'only', tone: 'accent' }])
  })

  test('a single value prefers the spec kpis when present', () => {
    const own = [{ label: 'X', value: '1' }]
    expect(degenerateKpis(spec({ data: [{ cat: 'only', v: 42 }], kpis: own }))).toBe(own)
  })

  test('a single value tolerates a null row and a missing category key', () => {
    const kpis = degenerateKpis(spec({ data: [{ v: null }, { v: 42 }] }))
    expect(kpis).toEqual([{ label: 'T', value: '42', sub: undefined, tone: 'accent' }])
  })

  test('a genuine single-row spec still becomes a KPI', () => {
    const kpis = degenerateKpis(spec({ data: [{ cat: 'solo', v: 7 }] }))
    expect(kpis).toEqual([{ label: 'T', value: '7', sub: 'solo', tone: 'accent' }])
  })

  test('a multi-row sparse chart with one numeric point stays a chart', () => {
    const sparse = spec({ data: [{ cat: 'a', v: 10 }, { cat: 'b', v: null }, { cat: 'c', v: null }] })
    expect(degenerateKpis(sparse)).toBeNull()
  })

  test('all-null single-series data yields a placeholder tile', () => {
    const kpis = degenerateKpis(spec({ data: [{ cat: 'a', v: null }] }))
    expect(kpis).toEqual([{ label: 'T', value: '–' }])
  })

  test('near-flat data downgrades to an approximate KPI', () => {
    const kpis = degenerateKpis(
      spec({ data: [{ cat: 'a', v: 100 }, { cat: 'b', v: 100 }, { cat: 'c', v: 100.1 }] }),
    )
    expect(kpis?.[0]).toMatchObject({ value: '≈ 100.1', sub: 'across all 3', tone: 'accent' })
  })

  test('near-flat data prefers the spec kpis when present', () => {
    const own = [{ label: 'X', value: '1' }]
    const kpis = degenerateKpis(
      spec({ data: [{ cat: 'a', v: 100 }, { cat: 'b', v: 100 }, { cat: 'c', v: 100 }], kpis: own }),
    )
    expect(kpis).toBe(own)
  })

  test('genuinely varying data is not degenerate', () => {
    expect(degenerateKpis(spec({ data: [{ cat: 'a', v: 1 }, { cat: 'b', v: 50 }, { cat: 'c', v: 99 }] }))).toBeNull()
  })

  test('data with a negative value skips the flat check', () => {
    expect(degenerateKpis(spec({ data: [{ cat: 'a', v: -1 }, { cat: 'b', v: 2 }, { cat: 'c', v: 3 }] }))).toBeNull()
  })
})

describe('normalizeChart', () => {
  test('leaves a small ranking untouched', () => {
    const s = spec({ type: 'hbar' })
    expect(normalizeChart(s)).toEqual({ spec: s, truncation: null })
  })

  test.each(['line', 'bar', 'grouped-bar'] as const)(
    'never reorders or truncates a %s chart, even when large',
    (type) => {
      const data = Array.from({ length: 40 }, (_, i) => ({ cat: `m${i}`, v: i }))
      const result = normalizeChart(spec({ type, data }))
      expect(result.truncation).toBeNull()
      expect(result.spec.data).toHaveLength(40)
    },
  )

  test('caps a large ranking to the largest N and reports it', () => {
    const data = Array.from({ length: 30 }, (_, i) => ({ cat: `c${i}`, v: i }))
    const { spec: out, truncation } = normalizeChart(spec({ type: 'hbar', data }))
    expect(out.data).toHaveLength(MAX_CATEGORY_BARS)
    expect(truncation).toEqual({ shown: MAX_CATEGORY_BARS, total: 30 })
    expect(out.data[0].v).toBe(29)
  })

  test('ranking uses absolute magnitude across series and tolerates nulls', () => {
    const data = Array.from({ length: 20 }, (_, i) => ({ cat: `c${i}`, v: i === 0 ? null : -i }))
    const { spec: out } = normalizeChart(spec({ type: 'delta', data }))
    expect(out.data[0].v).toBe(-19)
  })
})
