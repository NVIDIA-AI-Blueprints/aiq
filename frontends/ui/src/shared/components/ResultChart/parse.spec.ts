// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { fenceBareSpecs, parseCarouselSpec, parseChartSpec, parseKpiSpec, toNumber } from './parse'
import { ChartSpecSchema } from './types'

const barSpec = {
  type: 'bar',
  title: 'Fleet',
  x: { key: 'model' },
  series: [{ key: 'count' }],
  data: [
    { model: 'H100', count: 10 },
    { model: 'A100', count: 5 },
  ],
}
const lineSpec = { ...barSpec, type: 'line' }
const singleKeyRowSpec = {
  type: 'hbar',
  title: 'FY2025 Data Center Revenue Comparison',
  x: { key: 'revenue', label: 'Revenue (USD billions)' },
  y: { label: 'Company' },
  series: [{ key: 'revenue', color: 'green' }],
  data: [{ NVIDIA: 115.3 }, { AMD: 12.6 }, { Intel: 9.1 }],
}

describe('toNumber', () => {
  test('numbers pass through, non-finite becomes null', () => {
    expect(toNumber(42)).toBe(42)
    expect(toNumber(Infinity)).toBeNull()
  })

  test('numeric-ish strings are cleaned', () => {
    expect(toNumber('1,234')).toBe(1234)
    expect(toNumber('$1200')).toBe(1200)
  })

  test('a trailing percent is read as a fraction', () => {
    expect(toNumber('94%')).toBe(0.94)
    expect(toNumber('100%')).toBe(1)
  })

  test('empty, non-numeric, and other types are null', () => {
    expect(toNumber('')).toBeNull()
    expect(toNumber('abc')).toBeNull()
    expect(toNumber(null)).toBeNull()
    expect(toNumber({})).toBeNull()
  })
})

describe('parseChartSpec', () => {
  test('parses a valid spec', () => {
    expect(parseChartSpec(JSON.stringify(barSpec))?.type).toBe('bar')
  })

  test('malformed JSON returns null', () => {
    expect(parseChartSpec('{not json')).toBeNull()
  })

  test('schema failure returns null', () => {
    expect(parseChartSpec(JSON.stringify({ ...barSpec, series: [] }))).toBeNull()
  })

  test('null when the x key resolves on no row', () => {
    const spec = { ...barSpec, x: { key: 'missing' } }
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  test('null when no series has numeric data', () => {
    const spec = {
      ...barSpec,
      data: [
        { model: 'H100', count: 'n/a' },
        { model: 'A100', count: null },
      ],
    }
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  test('null when any series has no numeric data', () => {
    const spec = {
      ...barSpec,
      series: [{ key: 'count' }, { key: 'trend' }],
      data: [
        { model: 'H100', count: 10, trend: 'n/a' },
        { model: 'A100', count: 5, trend: null },
      ],
    }
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  test('repairs a single-key-row spec into a renderable chart', () => {
    const spec = parseChartSpec(JSON.stringify(singleKeyRowSpec))
    expect(spec).not.toBeNull()
    if (!spec) return
    expect(spec.data).toHaveLength(3)
    expect(spec.data.every((row) => row[spec.x.key] != null && row[spec.x.key] !== '')).toBe(true)
    expect(spec.series).toHaveLength(1)
    expect(spec.data.map((row) => toNumber(row[spec.series[0].key]))).toEqual([115.3, 12.6, 9.1])
    expect(spec.series[0].color).toBe('green')
  })

  test('single keys that match a declared field or repeat stay un-repairable', () => {
    const base = { ...singleKeyRowSpec, x: { key: 'company' }, series: [{ key: 'revenue', color: 'green' }] }
    const fieldNameKeyed = { ...base, data: [{ revenue: 115.3 }, { revenue: 12.6 }, { revenue: 9.1 }] }
    expect(parseChartSpec(JSON.stringify(fieldNameKeyed))).toBeNull()
    const repeatedLabel = { ...base, data: [{ Acme: 1 }, { Acme: 2 }] }
    expect(parseChartSpec(JSON.stringify(repeatedLabel))).toBeNull()
  })

  test('multi-series single-key-row specs stay un-repairable', () => {
    const multiSeries = {
      ...singleKeyRowSpec,
      x: { key: 'company' },
      series: [
        { key: 'q1', color: 'green' },
        { key: 'q2', color: 'blue' },
      ],
      data: [{ NVIDIA: 115.3 }, { AMD: 12.6 }, { Intel: 9.1 }],
    }
    expect(parseChartSpec(JSON.stringify(multiSeries))).toBeNull()
  })

  test('a well-formed spec is not altered by the repair fallback', () => {
    expect(parseChartSpec(JSON.stringify(barSpec))).toEqual(ChartSpecSchema.parse(barSpec))
  })

  test('rows with multiple keys and no matching x key stay un-repairable', () => {
    const spec = { ...barSpec, x: { key: 'missing' } }
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  test('carousel and kpi parsing are unaffected by the repair fallback', () => {
    const carousel = { title: 'Trends', charts: [lineSpec, lineSpec] }
    expect(parseCarouselSpec(JSON.stringify(carousel))?.charts).toHaveLength(2)
    expect(parseKpiSpec(JSON.stringify({ kpis: [{ label: 'A', value: '1' }] }))?.kpis).toHaveLength(1)
  })
})

describe('ChartSpecSchema delta refinement', () => {
  test('a delta chart accepts exactly one series', () => {
    const spec = { ...barSpec, type: 'delta', series: [{ key: 'count' }] }
    expect(ChartSpecSchema.safeParse(spec).success).toBe(true)
  })

  test('a delta chart with more than one series is rejected', () => {
    const spec = { ...barSpec, type: 'delta', series: [{ key: 'count' }, { key: 'other' }] }
    expect(ChartSpecSchema.safeParse(spec).success).toBe(false)
  })
})

describe('parseCarouselSpec', () => {
  test('parses a valid carousel', () => {
    const spec = { title: 'Trends', charts: [lineSpec, lineSpec] }
    expect(parseCarouselSpec(JSON.stringify(spec))?.charts).toHaveLength(2)
  })

  test('schema failure returns null', () => {
    expect(parseCarouselSpec(JSON.stringify({ title: 'x', charts: [lineSpec] }))).toBeNull()
  })

  test('null when a child chart has no usable data', () => {
    const badChild = { ...lineSpec, x: { key: 'missing' } }
    const spec = { title: 'Trends', charts: [lineSpec, badChild] }
    expect(parseCarouselSpec(JSON.stringify(spec))).toBeNull()
  })

  test('repairs a single-key-row child so the carousel renders it', () => {
    const singleKeyLine = { ...singleKeyRowSpec, type: 'line' }
    const spec = { title: 'Trends', charts: [lineSpec, singleKeyLine] }
    const parsed = parseCarouselSpec(JSON.stringify(spec))
    expect(parsed?.charts).toHaveLength(2)
    const repaired = parsed?.charts[1]
    expect(repaired?.x.key).toBe('category')
    expect(repaired?.data.every((row) => row['category'] != null && toNumber(row['value']) != null)).toBe(true)
  })
})

describe('parseKpiSpec', () => {
  test('valid and invalid', () => {
    expect(parseKpiSpec(JSON.stringify({ kpis: [{ label: 'A', value: '1' }] }))?.kpis).toHaveLength(1)
    expect(parseKpiSpec(JSON.stringify({ kpis: [] }))).toBeNull()
  })
})

describe('fenceBareSpecs', () => {
  test('returns markdown unchanged when it has no brace', () => {
    expect(fenceBareSpecs('just text')).toBe('just text')
  })

  test('leaves lines already inside a fence untouched', () => {
    const md = '```json\n' + JSON.stringify(barSpec) + '\n```'
    expect(fenceBareSpecs(md)).toBe(md)
  })

  test('fences a bare chart spec line', () => {
    const out = fenceBareSpecs('intro\n' + JSON.stringify(barSpec))
    expect(out).toContain('```chart\n')
  })

  test('fences a bare carousel spec line', () => {
    const carousel = { title: 'Trends', charts: [lineSpec, lineSpec] }
    const out = fenceBareSpecs(JSON.stringify(carousel))
    expect(out).toContain('```chart-carousel\n')
  })

  test('fences a bare kpi-only spec line', () => {
    const out = fenceBareSpecs(JSON.stringify({ kpis: [{ label: 'A', value: '1' }] }))
    expect(out).toContain('```chart\n')
  })

  test('ignores a brace line that is not a spec', () => {
    expect(fenceBareSpecs('{ "hello": 1 }')).toBe('{ "hello": 1 }')
  })
})
