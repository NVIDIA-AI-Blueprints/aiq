// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  ChartCarouselSpecSchema,
  ChartSpecSchema,
  KpiOnlySpecSchema,
  type ChartCarouselSpec,
  type ChartSeries,
  type ChartSpec,
  type KpiOnlySpec,
} from './types'

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/**
 * Coerce a cell value (number, or a numeric-ish string like "11,463" or "$1.2M")
 * to a number. A trailing "%" denotes a fraction, so "94%" becomes 0.94 to match
 * the `percent` format contract (data is fractions 0-1); "$", ",", and whitespace
 * are stripped without rescaling.
 */
export function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') {
    const isPercent = value.trimEnd().endsWith('%')
    const cleaned = value.replace(/[,$\s%]/g, '')
    if (cleaned === '') return null
    const parsed = Number(cleaned)
    if (!Number.isFinite(parsed)) return null
    return isPercent ? parsed / 100 : parsed
  }
  return null
}

/**
 * Whether a schema-valid spec has something meaningful to draw: the x key must
 * resolve on at least one row, and every series must carry at least one numeric
 * value (via {@link toNumber}).
 */
function isRenderable(spec: ChartSpec): boolean {
  const hasX = spec.data.some((row) => row[spec.x.key] != null && row[spec.x.key] !== '')
  if (!hasX) return false
  return spec.series.every((s) => spec.data.some((row) => toNumber(row[s.key]) != null))
}

/**
 * Deterministic repair for the shape weaker models sometimes emit, where each row
 * carries the category value as its object key (e.g. `{"NVIDIA":115.3}`) instead
 * of flat fields, so no key resolves. Applies only when every row is an object
 * with exactly one key whose value coerces to a number: it rewrites x.key to
 * "category", collapses to a single "value" series (preserving the first series'
 * color and label), and rebuilds each row as `{ category: <label>, value: <num> }`.
 * The repair is skipped (returns null, so the block falls back to raw JSON) for a
 * multi-series spec (this shape carries one value per row, so collapsing it would
 * hide the other declared series), or when a row key matches a declared field name
 * (x or a series key) or repeats across rows, since those indicate a different
 * broken spec that would otherwise become mislabeled or duplicated categories
 * rather than the intended category-as-key shape.
 */
function repairSingleKeyRows(spec: ChartSpec): ChartSpec | null {
  if (spec.series.length !== 1) return null
  const declaredKeys = new Set([spec.x.key, ...spec.series.map((s) => s.key)])
  const seenLabels = new Set<string>()
  const data: ChartSpec['data'] = []
  for (const row of spec.data) {
    const keys = Object.keys(row)
    if (keys.length !== 1) return null
    const label = keys[0]
    if (declaredKeys.has(label) || seenLabels.has(label)) return null
    const value = toNumber(row[label])
    if (value == null) return null
    seenLabels.add(label)
    data.push({ category: label, value })
  }
  const source = spec.series[0]
  const series: ChartSeries = { key: 'value' }
  if (source.label) series.label = source.label
  if (source.color) series.color = source.color
  return { ...spec, x: { ...spec.x, key: 'category' }, series: [series], data }
}

/**
 * Parse + validate a ```chart block's JSON into a {@link ChartSpec}. Returns null
 * (so the caller can fall back to the raw block) when the JSON is malformed, fails
 * the schema, or references keys with no usable data. A schema-valid spec whose
 * keys do not resolve is given one deterministic repair pass for the single-key
 * row shape before giving up.
 */
export function parseChartSpec(raw: string): ChartSpec | null {
  const parsed = ChartSpecSchema.safeParse(parseJson(raw))
  if (!parsed.success) return null
  const spec = parsed.data

  if (isRenderable(spec)) return spec

  const repaired = repairSingleKeyRows(spec)
  return repaired && isRenderable(repaired) ? repaired : null
}

/** Parse + validate a ```chart-carousel block of related line charts. */
export function parseCarouselSpec(raw: string): ChartCarouselSpec | null {
  const parsed = ChartCarouselSpecSchema.safeParse(parseJson(raw))
  if (!parsed.success) return null

  const charts: ChartCarouselSpec['charts'] = []
  for (const chart of parsed.data.charts) {
    const renderable = parseChartSpec(JSON.stringify(chart))
    if (!renderable) return null
    charts.push(renderable as ChartCarouselSpec['charts'][number])
  }
  return { ...parsed.data, charts }
}

/**
 * Parse a KPI-only block ({ title?, subtitle?, kpis }) with no chart axes/data.
 * Used for a single value or a one-entity result that is not worth a chart.
 */
export function parseKpiSpec(raw: string): KpiOnlySpec | null {
  const parsed = KpiOnlySpecSchema.safeParse(parseJson(raw))
  return parsed.success ? parsed.data : null
}

/**
 * The agent sometimes emits a chart spec as a bare JSON line instead of a fenced
 * ```chart block, which would render as raw JSON. Wrap any standalone line that is
 * a valid chart (or kpi-only) spec in the matching fence so it renders regardless.
 * Lines already inside a code fence are left untouched.
 */
export function fenceBareSpecs(markdown: string): string {
  if (!markdown.includes('{')) return markdown
  let inFence = false
  return markdown
    .split('\n')
    .map((line) => {
      if (line.trimStart().startsWith('```')) {
        inFence = !inFence
        return line
      }
      if (inFence) return line
      const trimmed = line.trim()
      if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        if (parseCarouselSpec(trimmed)) return '```chart-carousel\n' + trimmed + '\n```'
        if (parseChartSpec(trimmed) || parseKpiSpec(trimmed)) return '```chart\n' + trimmed + '\n```'
      }
      return line
    })
    .join('\n')
}
