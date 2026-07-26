// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { compactNumber, computeDomain, formatTick, formatValue, formatValueFull, niceCeil, ticks } from './scale'

describe('niceCeil', () => {
  test('non-positive and non-finite fall back to 1', () => {
    expect(niceCeil(0)).toBe(1)
    expect(niceCeil(-5)).toBe(1)
    expect(niceCeil(Infinity)).toBe(1)
    expect(niceCeil(NaN)).toBe(1)
  })

  test('rounds up to 1/2/5/10 x 10^n', () => {
    expect(niceCeil(1)).toBe(1)
    expect(niceCeil(0.8)).toBe(1)
    expect(niceCeil(1.5)).toBe(2)
    expect(niceCeil(3)).toBe(5)
    expect(niceCeil(7)).toBe(10)
    expect(niceCeil(45)).toBe(50)
    expect(niceCeil(120)).toBe(200)
  })
})

describe('computeDomain', () => {
  test('empty values default to 0..1', () => {
    expect(computeDomain([])).toEqual({ min: 0, max: 1 })
  })

  test('non-negative data gets a zero baseline and nice headroom', () => {
    expect(computeDomain([10, 90])).toEqual({ min: 0, max: 100 })
  })

  test('all-zero data gets max 1', () => {
    expect(computeDomain([0, 0])).toEqual({ min: 0, max: 1 })
  })

  test('percent data in 0..1 is pinned', () => {
    expect(computeDomain([0.1, 0.9], true)).toEqual({ min: 0, max: 1 })
  })

  test('percent flag but out-of-range falls through to nice bounds', () => {
    expect(computeDomain([1.5], true)).toEqual({ min: 0, max: 2 })
  })

  test('mixed-sign data gets nice bounds both sides', () => {
    expect(computeDomain([-30, 60])).toEqual({ min: -50, max: 100 })
  })

  test('all-negative data caps max at 0', () => {
    expect(computeDomain([-30, -5])).toEqual({ min: -50, max: 0 })
  })

  test('ignores non-finite values', () => {
    expect(computeDomain([NaN, 50])).toEqual({ min: 0, max: 100 })
  })
})

describe('ticks', () => {
  test('returns [min] when max is not greater than min', () => {
    expect(ticks(5, 5)).toEqual([5])
  })

  test('returns [min] when count < 1', () => {
    expect(ticks(0, 10, 0)).toEqual([0])
  })

  test('evenly spaced inclusive of both ends', () => {
    expect(ticks(0, 100, 4)).toEqual([0, 25, 50, 75, 100])
  })
})

describe('compactNumber', () => {
  test('non-finite renders as a placeholder', () => {
    expect(compactNumber(Infinity)).toBe('–')
  })

  test('scales to K/M/B and strips trailing .0', () => {
    expect(compactNumber(999)).toBe('999')
    expect(compactNumber(11463)).toBe('11.5K')
    expect(compactNumber(2000)).toBe('2K')
    expect(compactNumber(1_200_000)).toBe('1.2M')
    expect(compactNumber(2_000_000_000)).toBe('2B')
  })

  test('keeps the sign for negatives', () => {
    expect(compactNumber(-11463)).toBe('-11.5K')
  })
})

describe('formatValue', () => {
  test('non-finite renders as a placeholder', () => {
    expect(formatValue(NaN)).toBe('–')
  })

  test('percent formats integer vs fractional', () => {
    expect(formatValue(0.5, 'percent')).toBe('50%')
    expect(formatValue(0.945, 'percent')).toBe('94.5%')
  })

  test('compact, currency, and default', () => {
    expect(formatValue(11463, 'compact')).toBe('11.5K')
    expect(formatValue(11463, 'currency')).toBe('$11.5K')
    expect(formatValue(1234, 'number')).toBe('1,234')
  })
})

describe('formatTick', () => {
  test('compacts large plain numbers so they fit the axis', () => {
    expect(formatTick(2_000_000_000, 'number')).toBe('2B')
    expect(formatTick(50000, 'number')).toBe('50K')
  })

  test('keeps numbers below the compaction threshold verbatim', () => {
    expect(formatTick(1234, 'number')).toBe('1,234')
    expect(formatTick(5000, 'number')).toBe('5,000')
  })

  test('defers other formats to formatValue', () => {
    expect(formatTick(0.5, 'percent')).toBe('50%')
    expect(formatTick(2_000_000, 'currency')).toBe('$2M')
  })
})

describe('formatValueFull', () => {
  test('non-finite renders as a placeholder', () => {
    expect(formatValueFull(NaN)).toBe('–')
  })

  test('percent, currency, and default show full precision', () => {
    expect(formatValueFull(0.9456, 'percent')).toBe('94.56%')
    expect(formatValueFull(1234.5, 'currency')).toBe('$1,234.50')
    expect(formatValueFull(1234.5, 'number')).toBe('1,234.5')
  })
})
