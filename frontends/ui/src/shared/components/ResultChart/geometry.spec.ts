// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { CHART_WIDTH, chartHeight, plotBox, projectX, projectY } from './geometry'
import type { ChartSpec } from './types'

function spec(type: ChartSpec['type'], rows: number): ChartSpec {
  return {
    type,
    title: 'T',
    x: { key: 'c' },
    series: [{ key: 'v' }],
    data: Array.from({ length: rows }, (_, i) => ({ c: String(i), v: i })),
  } as ChartSpec
}

describe('plotBox', () => {
  test('uses default padding', () => {
    const box = plotBox(290)
    expect(box).toEqual({ x0: 54, x1: CHART_WIDTH - 18, y0: 256, y1: 18, w: CHART_WIDTH - 72, h: 238 })
  })

  test('honors custom gutters', () => {
    const box = plotBox(200, 132, 96)
    expect(box.x0).toBe(132)
    expect(box.x1).toBe(CHART_WIDTH - 96)
  })
})

describe('chartHeight', () => {
  test('vertical types are fixed height', () => {
    expect(chartHeight(spec('bar', 3))).toBe(290)
  })

  test('horizontal types grow with rows, clamped', () => {
    expect(chartHeight(spec('hbar', 5))).toBe(18 + 34 + 5 * 32)
    expect(chartHeight(spec('delta', 1))).toBe(140)
    expect(chartHeight(spec('hbar', 40))).toBe(560)
  })
})

describe('projection', () => {
  test('projectY maps min to baseline and max to top', () => {
    const box = plotBox(290)
    expect(projectY(0, box, 0, 100)).toBe(box.y0)
    expect(projectY(100, box, 0, 100)).toBe(box.y1)
  })

  test('projectX maps min to left and max to right', () => {
    const box = plotBox(290)
    expect(projectX(0, box, 0, 100)).toBe(box.x0)
    expect(projectX(100, box, 0, 100)).toBe(box.x1)
  })

  test('a zero span does not divide by zero', () => {
    const box = plotBox(290)
    expect(projectY(5, box, 5, 5)).toBe(box.y0)
    expect(projectX(5, box, 5, 5)).toBe(box.x0)
  })
})
