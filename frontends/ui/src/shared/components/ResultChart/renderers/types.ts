// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { PlotBox } from '../geometry'
import type { ChartSpec, ValueFormat } from '../types'

/** A single primitive drawing instruction. Renderers emit these; the shell maps them to SVG. */
export type Mark =
  | { kind: 'gridline'; x1: number; y1: number; x2: number; y2: number }
  | { kind: 'rect'; x: number; y: number; width: number; height: number; color: string; tip: string }
  | { kind: 'path'; d: string; variant: 'line' | 'area'; color: string }
  | { kind: 'dot'; cx: number; cy: number; color: string; tip: string }
  | {
      kind: 'text'
      x: number
      y: number
      text: string
      anchor: 'start' | 'middle' | 'end'
      variant: 'tick' | 'cat' | 'value' | 'unit'
    }

/** Everything a renderer needs; domain and colors are resolved once by the shell. */
export interface RenderInput {
  spec: ChartSpec
  box: PlotBox
  min: number
  max: number
  colors: string[]
  fmt: ValueFormat
}

export type Renderer = (input: RenderInput) => Mark[]
