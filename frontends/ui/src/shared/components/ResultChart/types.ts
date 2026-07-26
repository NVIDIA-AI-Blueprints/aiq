// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { z } from 'zod'

export const CHART_TYPES = ['bar', 'hbar', 'line', 'area', 'grouped-bar', 'delta'] as const
export const CHART_COLORS = ['green', 'blue', 'amber', 'red', 'neutral'] as const
export const VALUE_FORMATS = ['number', 'compact', 'percent', 'currency'] as const
export const KPI_TONES = ['default', 'accent', 'warn', 'alarm'] as const

const SeriesSchema = z.object({
  key: z.string().min(1),
  label: z.string().optional(),
  color: z.enum(CHART_COLORS).optional(),
})

const KpiSchema = z.object({
  label: z.string().min(1),
  value: z.string().min(1),
  sub: z.string().optional(),
  tone: z.enum(KPI_TONES).optional(),
})

const CellSchema = z.union([z.string(), z.number(), z.null()])

/**
 * The declarative chart the agent emits as a fenced ```chart JSON block. The
 * agent chooses the type, encodings, data and formatting; the frontend owns the
 * rendering style, dimensions and safe axis defaults.
 */
const ChartSpecObjectSchema = z.object({
  type: z.enum(CHART_TYPES),
  title: z.string().min(1),
  subtitle: z.string().optional(),
  x: z.object({ key: z.string().min(1), label: z.string().optional() }),
  y: z
    .object({ label: z.string().optional(), format: z.enum(VALUE_FORMATS).optional() })
    .optional(),
  series: z.array(SeriesSchema).min(1).max(6),
  data: z.array(z.record(z.string(), CellSchema)).min(1).max(60),
  kpis: z.array(KpiSchema).max(4).optional(),
})

/**
 * A `delta` chart colors its bars by sign with no legend, so it can encode only a
 * single series; more than one would be indistinguishable.
 */
export const ChartSpecSchema = ChartSpecObjectSchema.refine(
  (spec) => spec.type !== 'delta' || spec.series.length === 1,
  { message: 'a delta chart must declare exactly one series', path: ['series'] },
)

const LineChartSpecSchema = ChartSpecObjectSchema.extend({ type: z.literal('line') })

/** A pageable set of related line charts emitted in a ```chart-carousel block. */
export const ChartCarouselSpecSchema = z.object({
  title: z.string().min(1),
  charts: z.array(LineChartSpecSchema).min(2).max(12),
})

/**
 * A KPI-only block: headline tiles with no chart body. Emitted for a single
 * value or a one-entity yes/no result, where a chart would compare nothing.
 */
export const KpiOnlySpecSchema = z.object({
  title: z.string().optional(),
  subtitle: z.string().optional(),
  kpis: z.array(KpiSchema).min(1).max(4),
})

export type ChartSpec = z.infer<typeof ChartSpecSchema>
export type ChartCarouselSpec = z.infer<typeof ChartCarouselSpecSchema>
export type ChartSeries = z.infer<typeof SeriesSchema>
export type ChartKpi = z.infer<typeof KpiSchema>
export type KpiOnlySpec = z.infer<typeof KpiOnlySpecSchema>
export type ChartCell = z.infer<typeof CellSchema>
export type ChartType = (typeof CHART_TYPES)[number]
export type ChartColor = (typeof CHART_COLORS)[number]
export type ValueFormat = (typeof VALUE_FORMATS)[number]
export type KpiTone = (typeof KPI_TONES)[number]
