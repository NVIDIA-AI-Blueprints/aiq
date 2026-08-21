// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { projectX } from '../geometry'
import { GAIN, LOSS } from '../palette'
import { toNumber } from '../parse'
import { formatValue, formatValueFull } from '../scale'
import { horizontalAxis, truncate } from './axis'
import type { Mark, RenderInput } from './types'

/**
 * Horizontal bars with categories down the left edge, best for rankings with long
 * text labels. The `delta` variant is diverging: bars extend either side of the
 * zero line and are colored by sign (gain vs loss), so direction and color agree.
 */
export function renderHbar({ spec, box, min, max, colors, fmt }: RenderInput): Mark[] {
  const marks: Mark[] = horizontalAxis(box, min, max, fmt)
  const cats = spec.data.map((row) => String(row[spec.x.key] ?? ''))
  const diverging = spec.type === 'delta'
  const baseX = projectX(Math.max(min, 0), box, min, max)
  const band = box.h / Math.max(cats.length, 1)
  const seriesCount = spec.series.length
  const groupHeight = Math.min(26, band * 0.72)
  const slotHeight = groupHeight / seriesCount
  const barHeight = Math.max(slotHeight - (seriesCount > 1 ? 2 : 0), 2)

  cats.forEach((cat, i) => {
    const centerY = box.y1 + band * i + band / 2
    marks.push({ kind: 'text', x: box.x0 - 8, y: centerY + 3.5, text: truncate(cat, 22), anchor: 'end', variant: 'cat' })

    spec.series.forEach((series, si) => {
      const value = toNumber(spec.data[i][series.key])
      if (value == null) return
      const x = projectX(value, box, min, max)
      const y = centerY - groupHeight / 2 + slotHeight * si
      const color = diverging ? (value >= 0 ? GAIN : LOSS) : colors[si]
      const tip = `${cat}${seriesCount > 1 ? ` · ${series.label ?? series.key}` : ''}: ${formatValueFull(value, fmt)}`
      marks.push({
        kind: 'rect',
        x: Math.min(baseX, x),
        y,
        width: Math.abs(x - baseX),
        height: barHeight,
        color,
        tip,
      })
      if (seriesCount === 1) {
        marks.push({
          kind: 'text',
          x: x + (value >= 0 ? 6 : -6),
          y: centerY + 3.5,
          text: formatValue(value, fmt),
          anchor: value >= 0 ? 'start' : 'end',
          variant: 'value',
        })
      }
    })
  })

  return marks
}
