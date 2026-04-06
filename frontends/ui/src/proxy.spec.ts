// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { beforeEach, describe, expect, test, vi } from 'vitest'

const mockGetToken = vi.fn()
const mockCookiesSet = vi.fn()
const mockCookiesDelete = vi.fn()

vi.mock('next-auth/jwt', () => ({
  getToken: (...args: unknown[]) => mockGetToken(...args),
}))

vi.mock('next/server', () => ({
  NextResponse: {
    next: () => ({
      cookies: {
        set: mockCookiesSet,
        delete: mockCookiesDelete,
      },
    }),
  },
}))

vi.mock('@/adapters/auth/config', () => ({
  SESSION_MAX_AGE_SECONDS: 86400,
  isAuthRequired: () => true,
  shouldUseSecureCookies: () => true,
}))

import proxy from './proxy'

describe('proxy auth cookie management', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-02T12:00:00Z'))
    process.env.REQUIRE_AUTH = 'true'
    process.env.NEXTAUTH_SECRET = 'test-secret' // pragma: allowlist secret
  })

  test('sets idToken cookie with maxAge tracking real token TTL', async () => {
    const nowSec = Math.floor(Date.now() / 1000)
    mockGetToken.mockResolvedValue({
      idToken: 'valid-token-123',
      expiresAt: nowSec + 3600, // expires in 1 hour
    })

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesSet).toHaveBeenCalledWith(
      'idToken',
      'valid-token-123',
      expect.objectContaining({
        httpOnly: true,
        sameSite: 'lax',
        secure: true,
        maxAge: 3600, // matches real TTL, not fixed 24h
      })
    )
    expect(mockCookiesDelete).not.toHaveBeenCalledWith('idToken')
  })

  test('keeps cookie during refresh buffer window (not cleared early)', async () => {
    const nowSec = Math.floor(Date.now() / 1000)
    // Token expires in 60 seconds — within any reasonable refresh buffer,
    // but NOT actually expired. Cookie should still be set.
    mockGetToken.mockResolvedValue({
      idToken: 'almost-expired-token',
      expiresAt: nowSec + 60,
    })

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesSet).toHaveBeenCalledWith(
      'idToken',
      'almost-expired-token',
      expect.objectContaining({
        maxAge: 60,
      })
    )
    expect(mockCookiesDelete).not.toHaveBeenCalledWith('idToken')
  })

  test('clears cookie when token is actually expired', async () => {
    const nowSec = Math.floor(Date.now() / 1000)
    mockGetToken.mockResolvedValue({
      idToken: 'expired-token',
      expiresAt: nowSec - 10, // expired 10 seconds ago
    })

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesDelete).toHaveBeenCalledWith('idToken')
    expect(mockCookiesSet).not.toHaveBeenCalled()
  })

  test('clears cookie when refresh has already failed', async () => {
    mockGetToken.mockResolvedValue({
      error: 'RefreshAccessTokenError',
      idToken: 'stale-token',
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    })

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesDelete).toHaveBeenCalledWith('idToken')
    expect(mockCookiesSet).not.toHaveBeenCalled()
  })

  test('clears cookie when no token in session', async () => {
    mockGetToken.mockResolvedValue({
      // no idToken field
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    })

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesDelete).toHaveBeenCalledWith('idToken')
    expect(mockCookiesSet).not.toHaveBeenCalled()
  })

  test('clears cookie when getToken returns null', async () => {
    mockGetToken.mockResolvedValue(null)

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesDelete).toHaveBeenCalledWith('idToken')
    expect(mockCookiesSet).not.toHaveBeenCalled()
  })

  test('clamps maxAge to SESSION_MAX_AGE_SECONDS', async () => {
    const nowSec = Math.floor(Date.now() / 1000)
    mockGetToken.mockResolvedValue({
      idToken: 'long-lived-token',
      expiresAt: nowSec + 200000, // way beyond 24h
    })

    await proxy({
      nextUrl: { pathname: '/' },
    } as never)

    expect(mockCookiesSet).toHaveBeenCalledWith(
      'idToken',
      'long-lived-token',
      expect.objectContaining({
        maxAge: 86400, // clamped to SESSION_MAX_AGE_SECONDS
      })
    )
  })
})
