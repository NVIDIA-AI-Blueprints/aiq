// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { plotBox } from '../geometry'
import { GAIN, LOSS } from '../palette'
import type { ChartSpec } from '../types'
import { renderHbar } from './hbar'
import type { Mark, RenderInput } from './types'

function input(spec: ChartSpec, min: number, max: number, colors = ['#0a0', '#00a']): RenderInput {
  return { spec, box: plotBox(200, 132, 60), min, max, colors, fmt: 'number' }
}

const rects = (marks: Mark[]) => marks.filter((m) => m.kind === 'rect')
const values = (marks: Mark[]) => marks.filter((m) => m.kind === 'text' && m.variant === 'value')

describe('renderHbar', () => {
  test('single series draws bars with value labels and skips nulls', () => {
    const spec = {
      type: 'hbar',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [{ c: 'a', v: 40 }, { v: null }],
    } as unknown as ChartSpec

    const marks = renderHbar(input(spec, 0, 100))
    expect(rects(marks)).toHaveLength(1)
    expect(values(marks)).toHaveLength(1)
    expect(rects(marks)[0]).toMatchObject({ color: '#0a0' })
  })

  test('grouped hbar uses series colors and no value labels', () => {
    const spec = {
      type: 'hbar',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'a' }, { key: 'b' }],
      data: [{ c: 'x', a: 10, b: 20 }],
    } as unknown as ChartSpec

    const marks = renderHbar(input(spec, 0, 100))
    expect(rects(marks)).toHaveLength(2)
    expect(values(marks)).toHaveLength(0)
  })

  test('delta colors by sign and anchors labels by direction', () => {
    const spec = {
      type: 'delta',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [{ c: 'gain', v: 30 }, { c: 'loss', v: -20 }],
    } as unknown as ChartSpec

    const marks = renderHbar(input(spec, -50, 50))
    const colors = rects(marks).map((m) => (m.kind === 'rect' ? m.color : ''))
    expect(colors).toEqual([GAIN, LOSS])
    const anchors = values(marks).map((m) => (m.kind === 'text' ? m.anchor : ''))
    expect(anchors).toEqual(['start', 'end'])
  })
})
