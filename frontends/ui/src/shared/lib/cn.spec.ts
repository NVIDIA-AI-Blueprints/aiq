// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { cn } from './cn'

describe('cn', () => {
  test('joins truthy class names and drops falsy values', () => {
    expect(cn('a', false, 'b', undefined, null, 'c', 0 && 'd')).toBe('a b c')
  })

  test('later conflicting Tailwind utilities win', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4')
    expect(cn('rounded-sm', 'rounded-lg')).toBe('rounded-lg')
  })

  test('supports conditional object and array inputs', () => {
    expect(cn('base', { active: true, hidden: false }, ['x', 'y'])).toBe('base active x y')
  })
})
