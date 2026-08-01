// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { PlotBox } from '../geometry'
import { formatTick, ticks } from '../scale'
import type { ValueFormat } from '../types'
import type { Mark } from './types'

/** Truncate a label to `max` characters with an ellipsis. */
export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

/** Value-axis gridlines + tick labels along the left edge (vertical chart types). */
export function verticalAxis(
  box: PlotBox,
  min: number,
  max: number,
  fmt: ValueFormat,
  unit?: string,
): Mark[] {
  const marks: Mark[] = []
  const span = max - min || 1
  for (const value of ticks(min, max, 4)) {
    const y = box.y0 - ((value - min) / span) * box.h
    marks.push({ kind: 'gridline', x1: box.x0, y1: y, x2: box.x1, y2: y })
    marks.push({ kind: 'text', x: box.x0 - 8, y: y + 3.5, text: formatTick(value, fmt), anchor: 'end', variant: 'tick' })
  }
  if (unit) {
    marks.push({ kind: 'text', x: box.x0, y: box.y1 - 6, text: truncate(unit, 22), anchor: 'start', variant: 'unit' })
  }
  return marks
}

/** Value-axis gridlines + tick labels along the bottom edge (horizontal bar types). */
export function horizontalAxis(box: PlotBox, min: number, max: number, fmt: ValueFormat): Mark[] {
  const marks: Mark[] = []
  const span = max - min || 1
  for (const value of ticks(min, max, 4)) {
    const x = box.x0 + ((value - min) / span) * box.w
    marks.push({ kind: 'gridline', x1: x, y1: box.y1, x2: x, y2: box.y0 })
    marks.push({ kind: 'text', x, y: box.y0 + 16, text: formatTick(value, fmt), anchor: 'middle', variant: 'tick' })
  }
  return marks
}
