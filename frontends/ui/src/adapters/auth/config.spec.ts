// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, test, vi } from 'vitest'

const loadConfig = async () => {
  vi.resetModules()
  return import('./config')
}

describe('isAuthRequired', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  test('returns true when REQUIRE_AUTH is lowercase true', async () => {
    vi.stubEnv('REQUIRE_AUTH', 'true')
    const { isAuthRequired } = await loadConfig()
    expect(isAuthRequired()).toBe(true)
  })

  test('returns true when REQUIRE_AUTH is uppercase TRUE', async () => {
    vi.stubEnv('REQUIRE_AUTH', 'TRUE')
    const { isAuthRequired } = await loadConfig()
    expect(isAuthRequired()).toBe(true)
  })

  test('returns false when REQUIRE_AUTH is set to non-true value', async () => {
    vi.stubEnv('REQUIRE_AUTH', 'false')
    const { isAuthRequired } = await loadConfig()
    expect(isAuthRequired()).toBe(false)
  })
})

describe('auth timing config', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  test('uses defaults when timing env vars are unset', async () => {
    const { TOKEN_REFRESH_BUFFER_SECONDS, SESSION_MAX_AGE_SECONDS } = await loadConfig()

    expect(TOKEN_REFRESH_BUFFER_SECONDS).toBe(5 * 60)
    expect(SESSION_MAX_AGE_SECONDS).toBe(24 * 60 * 60)
  })

  test('falls back to defaults when timing env vars are invalid', async () => {
    vi.stubEnv('TOKEN_REFRESH_BUFFER_MINUTES', 'abc')
    vi.stubEnv('SESSION_MAX_AGE_HOURS', 'NaN')

    const { TOKEN_REFRESH_BUFFER_SECONDS, SESSION_MAX_AGE_SECONDS } = await loadConfig()

    expect(TOKEN_REFRESH_BUFFER_SECONDS).toBe(5 * 60)
    expect(SESSION_MAX_AGE_SECONDS).toBe(24 * 60 * 60)
  })

  test('falls back to defaults when timing env vars are non-positive', async () => {
    vi.stubEnv('TOKEN_REFRESH_BUFFER_MINUTES', '0')
    vi.stubEnv('SESSION_MAX_AGE_HOURS', '-1')

    const { TOKEN_REFRESH_BUFFER_SECONDS, SESSION_MAX_AGE_SECONDS } = await loadConfig()

    expect(TOKEN_REFRESH_BUFFER_SECONDS).toBe(5 * 60)
    expect(SESSION_MAX_AGE_SECONDS).toBe(24 * 60 * 60)
  })

  test('uses configured timing env vars when valid', async () => {
    vi.stubEnv('TOKEN_REFRESH_BUFFER_MINUTES', '30')
    vi.stubEnv('SESSION_MAX_AGE_HOURS', '12')

    const { TOKEN_REFRESH_BUFFER_SECONDS, SESSION_MAX_AGE_SECONDS } = await loadConfig()

    expect(TOKEN_REFRESH_BUFFER_SECONDS).toBe(30 * 60)
    expect(SESSION_MAX_AGE_SECONDS).toBe(12 * 60 * 60)
  })
})

describe('auth jwt refresh behavior', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  test('does not force refresh when refresh token exists but expiresAt is absent', async () => {
    const { authOptions } = await loadConfig()
    const token = {
      accessToken: 'access-token',
      refreshToken: 'refresh-token',
      userId: 'user-1',
    }

    const result = await authOptions.callbacks!.jwt!({
      token,
      account: null,
      user: {
        id: 'user-1',
        name: null,
        email: null,
        image: null,
      },
      profile: undefined,
      trigger: undefined,
      isNewUser: false,
      session: undefined,
    })

    expect(result).toEqual(token)
    expect(result.error).toBeUndefined()
  })
})
