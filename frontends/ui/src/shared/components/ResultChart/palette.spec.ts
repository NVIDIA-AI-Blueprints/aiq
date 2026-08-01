// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { GAIN, LOSS, PALETTE, seriesColor } from './palette'

describe('seriesColor', () => {
  test('honors an explicit color', () => {
    expect(seriesColor('blue', 0)).toBe(PALETTE.blue)
  })

  test('cycles through the default order when unset', () => {
    expect(seriesColor(undefined, 0)).toBe(PALETTE.green)
    expect(seriesColor(undefined, 1)).toBe(PALETTE.blue)
    expect(seriesColor(undefined, 5)).toBe(PALETTE.green)
  })
})

describe('diverging colors', () => {
  test('gain is brand green, loss is red', () => {
    expect(GAIN).toBe(PALETTE.green)
    expect(LOSS).toBe(PALETTE.red)
  })
})
