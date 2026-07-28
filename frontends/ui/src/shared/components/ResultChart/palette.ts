// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ChartColor } from './types'

/** Named series colors. Green is the NVIDIA brand token; the rest are theme-stable hexes. */
export const PALETTE: Record<ChartColor, string> = {
  green: 'var(--color-brand)',
  blue: '#4f9ff0',
  amber: '#e8b500',
  red: '#e5484d',
  neutral: 'var(--result-chart-neutral, #8c8c95)',
}

/** Default color assignment order when a series omits an explicit color. */
export const CYCLE: ChartColor[] = ['green', 'blue', 'amber', 'red', 'neutral']

/** Diverging colors for delta charts; gain/loss is also encoded by bar direction. */
export const GAIN = PALETTE.green
export const LOSS = PALETTE.red

/** Resolve the color for series `index`, honoring its explicit color or cycling. */
export function seriesColor(color: ChartColor | undefined, index: number): string {
  return PALETTE[color ?? CYCLE[index % CYCLE.length]]
}
