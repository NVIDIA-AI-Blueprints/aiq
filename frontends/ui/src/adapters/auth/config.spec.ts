// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, test, vi } from 'vitest'
import { isAuthRequired } from './config'

describe('isAuthRequired', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  test('returns true when REQUIRE_AUTH is lowercase true', () => {
    vi.stubEnv('REQUIRE_AUTH', 'true')
    expect(isAuthRequired()).toBe(true)
  })

  test('returns true when REQUIRE_AUTH is uppercase TRUE', () => {
    vi.stubEnv('REQUIRE_AUTH', 'TRUE')
    expect(isAuthRequired()).toBe(true)
  })

  test('returns false when REQUIRE_AUTH is set to non-true value', () => {
    vi.stubEnv('REQUIRE_AUTH', 'false')
    expect(isAuthRequired()).toBe(false)
  })
})
