// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { projectY } from '../geometry'
import { toNumber } from '../parse'
import { formatValueFull } from '../scale'
import { truncate, verticalAxis } from './axis'
import type { Mark, RenderInput } from './types'

/**
 * Line or area chart across an ordered axis. Missing values break the line into
 * segments (a gap, never an implied zero); the area variant fills the first
 * series down to the baseline.
 */
export function renderLine({ spec, box, min, max, colors, fmt }: RenderInput): Mark[] {
  const marks: Mark[] = verticalAxis(box, min, max, fmt, spec.y?.label)
  const cats = spec.data.map((row) => String(row[spec.x.key] ?? ''))
  const baselineY = projectY(Math.max(min, 0), box, min, max)
  const columnX = (i: number): number =>
    cats.length === 1 ? box.x0 + box.w / 2 : box.x0 + (i / (cats.length - 1)) * box.w

  spec.series.forEach((series, si) => {
    // Split into contiguous runs of present points so a missing value breaks the
    // line (a gap), never bridges across it as an implied straight trend.
    const segments: { x: number; y: number; value: number; i: number }[][] = []
    let run: { x: number; y: number; value: number; i: number }[] = []
    spec.data.forEach((row, i) => {
      const value = toNumber(row[series.key])
      if (value == null) {
        if (run.length) segments.push(run)
        run = []
        return
      }
      run.push({ x: columnX(i), y: projectY(value, box, min, max), value, i })
    })
    if (run.length) segments.push(run)

    for (const segment of segments) {
      if (segment.length < 2) continue
      const line = segment.map((p, k) => `${k === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
      if (spec.type === 'area' && si === 0) {
        const last = segment[segment.length - 1]
        const area = `${line} L ${last.x.toFixed(1)} ${baselineY.toFixed(1)} L ${segment[0].x.toFixed(1)} ${baselineY.toFixed(1)} Z`
        marks.push({ kind: 'path', d: area, variant: 'area', color: colors[si] })
      }
      marks.push({ kind: 'path', d: line, variant: 'line', color: colors[si] })
    }
    for (const segment of segments) {
      for (const p of segment) {
        marks.push({
          kind: 'dot',
          cx: p.x,
          cy: p.y,
          color: colors[si],
          tip: `${cats[p.i]} · ${series.label ?? series.key}: ${formatValueFull(p.value, fmt)}`,
        })
      }
    }
  })

  const step = cats.length <= 10 ? 1 : Math.ceil(cats.length / 8)
  const labelLimit = cats.length <= 6 ? 16 : 10
  cats.forEach((cat, i) => {
    if (i % step !== 0) return
    marks.push({ kind: 'text', x: columnX(i), y: box.y0 + 16, text: truncate(cat, labelLimit), anchor: 'middle', variant: 'cat' })
  })

  return marks
}
