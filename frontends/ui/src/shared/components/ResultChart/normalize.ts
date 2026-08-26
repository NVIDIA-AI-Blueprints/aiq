// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { toNumber } from './parse'
import { formatValue } from './scale'
import type { ChartKpi, ChartSpec, ChartType } from './types'

/** Below this relative spread a single-series chart's bars are visually identical. */
const FLAT_SPREAD = 0.005
/** Categorical charts beyond this many rows are truncated to the largest N. */
export const MAX_CATEGORY_BARS = 15
/**
 * Ranking types where sorting by magnitude and dropping the tail is meaningful.
 * Deliberately excludes `bar`/`grouped-bar`, whose x-axis order is often
 * categorical or temporal and must not be silently reordered.
 */
const TRUNCATABLE: readonly ChartType[] = ['hbar', 'delta']

export interface Truncation {
  shown: number
  total: number
}

export interface NormalizedChart {
  spec: ChartSpec
  truncation: Truncation | null
}

function numericValues(spec: ChartSpec, key: string): number[] {
  return spec.data.map((row) => toNumber(row[key])).filter((v): v is number => v != null)
}

/** Largest absolute series value in a row, used to rank rows for truncation. */
function rowMagnitude(spec: ChartSpec, row: ChartSpec['data'][number]): number {
  return Math.max(0, ...spec.series.map((s) => Math.abs(toNumber(row[s.key]) ?? 0)))
}

/**
 * When a single-series chart would compare nothing, return the KPI tiles to show
 * instead; otherwise return null (draw the chart). Two objective cases: a single
 * plotted point (only one row carries the x key), or a near-constant metric where
 * every bar is the same height. A multi-row chart with sparse values stays a
 * chart so its missing points render as gaps. Prefers the spec's own `kpis`.
 */
export function degenerateKpis(spec: ChartSpec): ChartKpi[] | null {
  if (spec.series.length !== 1) return null
  const key = spec.series[0].key
  const fmt = spec.y?.format ?? 'number'
  const values = numericValues(spec, key)
  const points = spec.data.filter((row) => row[spec.x.key] != null && row[spec.x.key] !== '').length

  if (points <= 1) {
    if (spec.kpis && spec.kpis.length > 0) return spec.kpis
    const row = spec.data.find((r) => toNumber(r[key]) != null)
    if (!row) return [{ label: spec.title, value: '–' }]
    const cat = String(row[spec.x.key] ?? '')
    return [{ label: spec.title, value: formatValue(values[0], fmt), sub: cat || undefined, tone: 'accent' }]
  }

  if (values.length >= 3 && values.every((v) => v >= 0)) {
    const max = Math.max(...values)
    const min = Math.min(...values)
    if (max > 0 && (max - min) / max < FLAT_SPREAD) {
      if (spec.kpis && spec.kpis.length > 0) return spec.kpis
      return [
        {
          label: spec.title,
          value: `≈ ${formatValue(max, fmt)}`,
          sub: `across all ${values.length}`,
          tone: 'accent',
        },
      ]
    }
  }

  return null
}

/**
 * Cap a ranking chart to the {@link MAX_CATEGORY_BARS} largest rows so a huge
 * result never renders as an unreadable wall of bars. Only rankings (`hbar`,
 * `delta`) are ranked and truncated; `bar`/`grouped-bar`/`line`/`area` keep every
 * row and their original order. The caller surfaces `truncation` as a caption so
 * dropped rows are always disclosed, never silent.
 */
export function normalizeChart(spec: ChartSpec): NormalizedChart {
  if (!TRUNCATABLE.includes(spec.type) || spec.data.length <= MAX_CATEGORY_BARS) {
    return { spec, truncation: null }
  }
  const ranked = [...spec.data]
    .sort((a, b) => rowMagnitude(spec, b) - rowMagnitude(spec, a))
    .slice(0, MAX_CATEGORY_BARS)
  return { spec: { ...spec, data: ranked }, truncation: { shown: ranked.length, total: spec.data.length } }
}
