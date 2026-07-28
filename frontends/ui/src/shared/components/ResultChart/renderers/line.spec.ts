// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { plotBox } from '../geometry'
import type { ChartSpec } from '../types'
import { renderLine } from './line'
import type { Mark, RenderInput } from './types'

function input(spec: ChartSpec, colors = ['#0a0', '#00a']): RenderInput {
  return { spec, box: plotBox(290), min: 0, max: 100, colors, fmt: 'number' }
}

const kinds = (marks: Mark[], kind: Mark['kind']) => marks.filter((m) => m.kind === kind)
const paths = (marks: Mark[]) => marks.filter((m): m is Extract<Mark, { kind: 'path' }> => m.kind === 'path')

describe('renderLine', () => {
  test('breaks the line into separate segments at a null, not one bridging line', () => {
    const spec = {
      type: 'line',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [
        { c: 'jan', v: 10 },
        { v: null },
        { c: 'mar', v: 30 },
        { c: 'apr', v: 35 },
      ],
    } as unknown as ChartSpec

    const marks = renderLine(input(spec))
    // 3 present points => 3 dots; the leading point is isolated (no 2+ run) so
    // only the mar-apr run draws a line path. The gap is never bridged.
    expect(kinds(marks, 'dot')).toHaveLength(3)
    const lines = paths(marks).filter((p) => p.variant === 'line')
    expect(lines).toHaveLength(1)
    expect(lines[0].d.split('M').length - 1).toBe(1)
  })

  test('draws multiple line segments around an interior gap', () => {
    const spec = {
      type: 'line',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [
        { c: 'jan', v: 10 },
        { c: 'feb', v: 20 },
        { c: 'mar', v: null },
        { c: 'apr', v: 40 },
        { c: 'may', v: 50 },
      ],
    } as unknown as ChartSpec

    const marks = renderLine(input(spec))
    expect(paths(marks).filter((p) => p.variant === 'line')).toHaveLength(2)
    expect(kinds(marks, 'dot')).toHaveLength(4)
  })

  test('area fills the first series to the baseline', () => {
    const spec = {
      type: 'area',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [{ c: 'a', v: 10 }, { c: 'b', v: 40 }],
    } as unknown as ChartSpec

    expect(paths(renderLine(input(spec))).some((p) => p.variant === 'area' && p.d.endsWith('Z'))).toBe(true)
  })

  test('centers a single-point series', () => {
    const spec = {
      type: 'line',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [{ c: 'only', v: 50 }],
    } as unknown as ChartSpec

    const dot = kinds(renderLine(input(spec)), 'dot')[0]
    expect(dot.kind === 'dot' && dot.cx).toBe(plotBox(290).x0 + plotBox(290).w / 2)
  })

  test('a fully-null series draws nothing for that series', () => {
    const spec = {
      type: 'line',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'a' }, { key: 'b' }],
      data: [{ c: 'x', a: 10, b: null }, { c: 'y', a: 20, b: null }],
    } as unknown as ChartSpec

    expect(paths(renderLine(input(spec)).filter((m) => m.kind === 'path'))).toHaveLength(1)
  })

  test('thins x labels when crowded', () => {
    const data = Array.from({ length: 16 }, (_, i) => ({ c: `m${i}`, v: i }))
    const spec = { type: 'line', title: 'T', x: { key: 'c' }, series: [{ key: 'v' }], data } as unknown as ChartSpec
    expect(kinds(renderLine(input(spec)), 'text').filter((m) => m.kind === 'text' && m.variant === 'cat').length).toBeLessThan(16)
  })
})
