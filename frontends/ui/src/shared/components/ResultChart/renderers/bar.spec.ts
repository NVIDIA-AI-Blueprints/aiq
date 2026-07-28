// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { plotBox, projectY } from '../geometry'
import type { ChartSpec } from '../types'
import { renderBar } from './bar'
import type { Mark, RenderInput } from './types'

function input(spec: ChartSpec, colors = ['#0a0', '#00a']): RenderInput {
  return { spec, box: plotBox(290), min: 0, max: 100, colors, fmt: 'number' }
}

const rects = (marks: Mark[]) => marks.filter((m) => m.kind === 'rect')
const values = (marks: Mark[]) => marks.filter((m) => m.kind === 'text' && m.variant === 'value')

describe('renderBar', () => {
  test('single series draws one bar and one value label per row, skipping nulls', () => {
    const spec = {
      type: 'bar',
      title: 'T',
      y: { label: 'GPUs' },
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [{ c: 'a', v: 40 }, { v: null }, { c: 'd', v: 80 }],
    } as unknown as ChartSpec

    const marks = renderBar(input(spec))
    expect(rects(marks)).toHaveLength(2)
    expect(values(marks)).toHaveLength(2)
    expect(marks.some((m) => m.kind === 'text' && m.variant === 'unit')).toBe(true)
  })

  test('places a negative single-series value label below the zero baseline', () => {
    const spec = {
      type: 'bar',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'v' }],
      data: [{ c: 'a', v: 50 }, { c: 'b', v: -30 }],
    } as unknown as ChartSpec
    const box = plotBox(290)
    const marks = renderBar({ spec, box, min: -50, max: 100, colors: ['#0a0'], fmt: 'number' })
    const labels = marks.filter((m) => m.kind === 'text' && m.variant === 'value')
    expect(labels).toHaveLength(2)
    const baselineY = projectY(0, box, -50, 100)
    const positive = labels.find((m) => m.kind === 'text' && m.text === '50')
    const negative = labels.find((m) => m.kind === 'text' && m.text === '-30')
    expect(positive?.kind === 'text' && positive.y).toBeLessThan(baselineY)
    expect(negative?.kind === 'text' && negative.y).toBeGreaterThan(baselineY)
  })

  test('grouped bars use one color per series and omit value labels', () => {
    const spec = {
      type: 'grouped-bar',
      title: 'T',
      x: { key: 'c' },
      series: [{ key: 'a' }, { key: 'b' }],
      data: [{ c: 'x', a: 10, b: 20 }, { c: 'y', a: 30, b: 40 }],
    } as unknown as ChartSpec

    const marks = renderBar(input(spec))
    expect(rects(marks)).toHaveLength(4)
    expect(values(marks)).toHaveLength(0)
    expect(rects(marks).map((m) => (m.kind === 'rect' ? m.color : ''))).toContain('#00a')
  })

  test('thins category labels when crowded', () => {
    const data = Array.from({ length: 16 }, (_, i) => ({ c: `c${i}`, v: i + 1 }))
    const spec = { type: 'bar', title: 'T', x: { key: 'c' }, series: [{ key: 'v' }], data } as unknown as ChartSpec
    const cats = renderBar(input(spec)).filter((m) => m.kind === 'text' && m.variant === 'cat')
    expect(cats.length).toBeLessThan(16)
  })
})
