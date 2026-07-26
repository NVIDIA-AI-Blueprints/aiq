// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { projectY } from '../geometry'
import { toNumber } from '../parse'
import { formatValue, formatValueFull } from '../scale'
import { truncate, verticalAxis } from './axis'
import type { Mark, RenderInput } from './types'

/**
 * Vertical bars, single-series or grouped. Bars rise from a zero baseline (or
 * the axis minimum when data dips negative); single-series bars carry a value
 * label, grouped bars rely on the legend and tooltip.
 */
export function renderBar({ spec, box, min, max, colors, fmt }: RenderInput): Mark[] {
  const marks: Mark[] = verticalAxis(box, min, max, fmt, spec.y?.label)
  const cats = spec.data.map((row) => String(row[spec.x.key] ?? ''))
  const baselineY = projectY(Math.max(min, 0), box, min, max)
  const band = box.w / Math.max(cats.length, 1)
  const seriesCount = spec.series.length
  const groupWidth = band * 0.7
  const barWidth = groupWidth / seriesCount

  cats.forEach((cat, i) => {
    const center = box.x0 + band * i + band / 2
    spec.series.forEach((series, si) => {
      const value = toNumber(spec.data[i][series.key])
      if (value == null) return
      const x = center - groupWidth / 2 + barWidth * si
      const y = projectY(value, box, min, max)
      const tip = `${cat}${seriesCount > 1 ? ` · ${series.label ?? series.key}` : ''}: ${formatValueFull(value, fmt)}`
      marks.push({
        kind: 'rect',
        x,
        y: Math.min(y, baselineY),
        width: Math.max(barWidth - 2, 1),
        height: Math.max(Math.abs(baselineY - y), 0.5),
        color: colors[si],
        tip,
      })
      if (seriesCount === 1) {
        const labelY = value >= 0 ? Math.min(y, baselineY) - 5 : Math.max(y, baselineY) + 12
        marks.push({ kind: 'text', x: center, y: labelY, text: formatValue(value, fmt), anchor: 'middle', variant: 'value' })
      }
    })
  })

  const step = cats.length <= 10 ? 1 : Math.ceil(cats.length / 8)
  const labelLimit = cats.length <= 6 ? 16 : 10
  cats.forEach((cat, i) => {
    if (i % step !== 0) return
    marks.push({ kind: 'text', x: box.x0 + band * i + band / 2, y: box.y0 + 16, text: truncate(cat, labelLimit), anchor: 'middle', variant: 'cat' })
  })

  return marks
}
