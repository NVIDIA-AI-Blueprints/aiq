// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ChartType } from '../types'
import { renderBar } from './bar'
import { renderHbar } from './hbar'
import { renderLine } from './line'
import type { Renderer } from './types'

/** Maps each chart type to its pure renderer. New types plug in here only. */
export const RENDERERS: Record<ChartType, Renderer> = {
  bar: renderBar,
  'grouped-bar': renderBar,
  hbar: renderHbar,
  delta: renderHbar,
  line: renderLine,
  area: renderLine,
}

export type { Mark, RenderInput, Renderer } from './types'
