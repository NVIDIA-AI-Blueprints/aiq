// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { CHART_TYPES } from '../types'
import { RENDERERS } from './index'
import { renderBar } from './bar'
import { renderHbar } from './hbar'
import { renderLine } from './line'

describe('RENDERERS', () => {
  test('maps every chart type to a renderer', () => {
    for (const type of CHART_TYPES) {
      expect(RENDERERS[type]).toBeTypeOf('function')
    }
  })

  test('routes types to the correct renderer', () => {
    expect(RENDERERS.bar).toBe(renderBar)
    expect(RENDERERS['grouped-bar']).toBe(renderBar)
    expect(RENDERERS.hbar).toBe(renderHbar)
    expect(RENDERERS.delta).toBe(renderHbar)
    expect(RENDERERS.line).toBe(renderLine)
    expect(RENDERERS.area).toBe(renderLine)
  })
})
