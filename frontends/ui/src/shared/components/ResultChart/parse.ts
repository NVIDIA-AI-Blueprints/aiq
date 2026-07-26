// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  ChartCarouselSpecSchema,
  ChartSpecSchema,
  KpiOnlySpecSchema,
  type ChartCarouselSpec,
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
 * Parse + validate a ```chart block's JSON into a {@link ChartSpec}. Returns null
 * (so the caller can fall back to the raw block) when the JSON is malformed, fails
 * the schema, or references keys with no usable data.
 */
export function parseChartSpec(raw: string): ChartSpec | null {
  const parsed = ChartSpecSchema.safeParse(parseJson(raw))
  if (!parsed.success) return null
  const spec = parsed.data

  // The x key must resolve on at least one row, and every series must carry at
  // least one numeric value, otherwise there is nothing meaningful to draw.
  const hasX = spec.data.some((row) => row[spec.x.key] != null && row[spec.x.key] !== '')
  if (!hasX) return null
  const everySeriesNumeric = spec.series.every((s) => spec.data.some((row) => toNumber(row[s.key]) != null))
  if (!everySeriesNumeric) return null

  return spec
}

/** Parse + validate a ```chart-carousel block of related line charts. */
export function parseCarouselSpec(raw: string): ChartCarouselSpec | null {
  const parsed = ChartCarouselSpecSchema.safeParse(parseJson(raw))
  if (!parsed.success) return null

  for (const chart of parsed.data.charts) {
    if (!parseChartSpec(JSON.stringify(chart))) return null
  }
  return parsed.data
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
