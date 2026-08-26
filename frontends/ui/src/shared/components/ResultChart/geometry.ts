// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ChartSpec } from './types'

/** Fixed SVG viewBox width; charts scale responsively to their container. */
export const CHART_WIDTH = 760
export const PAD = { l: 54, r: 18, t: 18, b: 34 } as const

/** The inner plotting rectangle (axes excluded) for a given height and gutters. */
export interface PlotBox {
  x0: number
  x1: number
  y0: number
  y1: number
  w: number
  h: number
}

export function plotBox(height: number, padLeft: number = PAD.l, padRight: number = PAD.r): PlotBox {
  return {
    x0: padLeft,
    x1: CHART_WIDTH - padRight,
    y0: height - PAD.b,
    y1: PAD.t,
    w: CHART_WIDTH - padLeft - padRight,
    h: height - PAD.b - PAD.t,
  }
}

/** Horizontal-bar charts grow with row count; every other type has a fixed height. */
export function chartHeight(spec: ChartSpec): number {
  if (spec.type === 'hbar' || spec.type === 'delta') {
    return Math.max(140, Math.min(560, PAD.t + PAD.b + spec.data.length * 32))
  }
  return 290
}

/** Project a value onto the vertical axis (y grows downward). */
export function projectY(value: number, box: PlotBox, min: number, max: number): number {
  const span = max - min || 1
  return box.y0 - ((value - min) / span) * box.h
}

/** Project a value onto the horizontal axis. */
export function projectX(value: number, box: PlotBox, min: number, max: number): number {
  const span = max - min || 1
  return box.x0 + ((value - min) / span) * box.w
}
