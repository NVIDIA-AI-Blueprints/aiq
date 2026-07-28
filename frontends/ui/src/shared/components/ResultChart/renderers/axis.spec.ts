// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { plotBox } from '../geometry'
import { horizontalAxis, truncate, verticalAxis } from './axis'

describe('truncate', () => {
  test('shortens with an ellipsis only when over the limit', () => {
    expect(truncate('short', 10)).toBe('short')
    expect(truncate('a-very-long-label', 8)).toBe('a-very-…')
  })
})

describe('verticalAxis', () => {
  const box = plotBox(290)

  test('emits a gridline and tick per value', () => {
    const marks = verticalAxis(box, 0, 100, 'number')
    expect(marks.filter((m) => m.kind === 'gridline')).toHaveLength(5)
    expect(marks.filter((m) => m.kind === 'text')).toHaveLength(5)
  })

  test('adds a unit label when provided', () => {
    const marks = verticalAxis(box, 0, 100, 'number', 'GPUs')
    expect(marks.some((m) => m.kind === 'text' && m.variant === 'unit')).toBe(true)
  })

  test('tolerates a zero span', () => {
    expect(verticalAxis(box, 5, 5, 'number')).toHaveLength(2)
  })
})

describe('horizontalAxis', () => {
  test('emits gridlines and bottom ticks', () => {
    const marks = horizontalAxis(plotBox(200, 132, 40), 0, 50, 'number')
    expect(marks.filter((m) => m.kind === 'gridline')).toHaveLength(5)
    expect(marks.filter((m) => m.kind === 'text' && m.variant === 'tick')).toHaveLength(5)
  })

  test('tolerates a zero span', () => {
    expect(horizontalAxis(plotBox(200, 132, 40), 5, 5, 'number')).toHaveLength(2)
  })
})
