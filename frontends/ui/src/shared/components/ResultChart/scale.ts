// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ValueFormat } from './types'

/**
 * Round a positive value up to a "nice" axis bound (1, 2, 5 x 10^n), so axes end
 * on readable numbers.
 */
export function niceCeil(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1
  const exponent = Math.pow(10, Math.floor(Math.log10(value)))
  const mantissa = value / exponent
  const nice = mantissa <= 1 ? 1 : mantissa <= 2 ? 2 : mantissa <= 5 ? 5 : 10
  return nice * exponent
}

/**
 * Compute a sensible [min, max] domain for a set of values. Non-negative data
 * gets a 0 baseline (the natural reading for counts / amounts / probabilities)
 * and a nice upper bound with a little headroom; data that dips negative gets
 * nice bounds on both sides. `percent` data already in 0-1 is pinned to 0-1.
 */
export function computeDomain(values: number[], percent = false): { min: number; max: number } {
  const finite = values.filter((v) => Number.isFinite(v))
  if (finite.length === 0) return { min: 0, max: 1 }
  const lo = Math.min(...finite)
  const hi = Math.max(...finite)

  if (percent && lo >= 0 && hi <= 1) return { min: 0, max: 1 }

  if (lo >= 0) {
    return { min: 0, max: hi > 0 ? niceCeil(hi * 1.08) : 1 }
  }
  return {
    min: -niceCeil(-lo * 1.08),
    max: hi > 0 ? niceCeil(hi * 1.08) : 0,
  }
}

/** Evenly-spaced tick values across [min, max] (inclusive of both ends). */
export function ticks(min: number, max: number, count = 4): number[] {
  if (!(max > min) || count < 1) return [min]
  const step = (max - min) / count
  return Array.from({ length: count + 1 }, (_, i) => min + step * i)
}

function localeNumber(value: number, maxFractionDigits = 2): string {
  return value.toLocaleString('en-US', {
    maximumFractionDigits: Number.isInteger(value) ? 0 : maxFractionDigits,
  })
}

/** One decimal place, with a trailing ".0" stripped (11.5 -> "11.5", 11.0 -> "11"). */
function oneDecimal(value: number): string {
  const text = value.toFixed(1)
  return text.endsWith('.0') ? text.slice(0, -2) : text
}

/** 11463 -> "11.5K", 1_200_000 -> "1.2M", 2e9 -> "2B"; < 1000 falls back to a plain number. */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '–'
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}${oneDecimal(abs / 1e9)}B`
  if (abs >= 1e6) return `${sign}${oneDecimal(abs / 1e6)}M`
  if (abs >= 1e3) return `${sign}${oneDecimal(abs / 1e3)}K`
  return localeNumber(value)
}

/** Format a value for an axis tick / label, per the spec's `y.format` (compact for space). */
export function formatValue(value: number, format: ValueFormat = 'number'): string {
  if (!Number.isFinite(value)) return '–'
  switch (format) {
    case 'percent': {
      const pct = value * 100
      return `${Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(1)}%`
    }
    case 'compact':
      return compactNumber(value)
    case 'currency':
      return `$${compactNumber(value)}`
    default:
      return localeNumber(value)
  }
}

/**
 * Format a value for an axis tick. Large plain numbers are compacted so they fit
 * the axis gutter ("2,000,000,000" -> "2B"); every other format defers to
 * {@link formatValue} (currency already compacts, percent stays short).
 */
export function formatTick(value: number, format: ValueFormat = 'number'): string {
  if (format === 'number' && Math.abs(value) >= 10000) return compactNumber(value)
  return formatValue(value, format)
}

/** Format the exact value (never abbreviated) for hover tooltips, in the best human-readable form. */
export function formatValueFull(value: number, format: ValueFormat = 'number'): string {
  if (!Number.isFinite(value)) return '–'
  switch (format) {
    case 'percent': {
      const pct = value * 100
      return `${pct.toLocaleString('en-US', { maximumFractionDigits: 2 })}%`
    }
    case 'currency':
      return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
    default:
      return localeNumber(value)
  }
}
