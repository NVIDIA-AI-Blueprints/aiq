// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import {
  getIdTokenCookieDecision,
  idTokenCookieMaxAgeSeconds,
  isTokenExpired,
} from './id-token-cookie'

describe('idToken cookie decisions', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-02T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  test('sets cookie when idToken exists and expires in the future', () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 3600

    expect(
      getIdTokenCookieDecision({
        idToken: 'id-token',
        expiresAt,
      })
    ).toBe('set')
  })

  test('deletes cookie when refresh has failed', () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 3600

    expect(
      getIdTokenCookieDecision({
        tokenError: 'RefreshAccessTokenError',
        idToken: 'stale-id-token',
        expiresAt,
      })
    ).toBe('delete')
  })

  test('deletes cookie when dev token has expired', () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 3600

    expect(
      getIdTokenCookieDecision({
        tokenError: 'DevTokenExpired',
        idToken: 'stale-id-token',
        expiresAt,
      })
    ).toBe('delete')
  })

  test('deletes cookie when idToken is missing', () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 3600

    expect(getIdTokenCookieDecision({ expiresAt })).toBe('delete')
  })

  test('deletes cookie when token expiry is missing', () => {
    expect(getIdTokenCookieDecision({ idToken: 'id-token' })).toBe('delete')
  })

  test('deletes cookie when token expiry is zero', () => {
    expect(getIdTokenCookieDecision({ idToken: 'id-token', expiresAt: 0 })).toBe('delete')
  })

  test('deletes cookie when token is expired by default', () => {
    const expiresAt = Math.floor(Date.now() / 1000) - 10

    expect(
      getIdTokenCookieDecision({
        idToken: 'expired-id-token',
        expiresAt,
      })
    ).toBe('delete')
  })

  test('preserves cookie for expired request token during session refresh', () => {
    const expiresAt = Math.floor(Date.now() / 1000) - 10

    expect(
      getIdTokenCookieDecision({
        idToken: 'request-side-id-token',
        expiresAt,
        preserveExpiredRequestToken: true,
      })
    ).toBe('preserve')
  })

  test('checks real token expiry', () => {
    const nowSec = Math.floor(Date.now() / 1000)

    expect(isTokenExpired(nowSec + 1)).toBe(false)
    expect(isTokenExpired(nowSec)).toBe(true)
    expect(isTokenExpired(0)).toBe(true)
    expect(isTokenExpired(undefined)).toBe(true)
  })

  test('clamps cookie maxAge to session lifetime', () => {
    const nowSec = Math.floor(Date.now() / 1000)

    expect(idTokenCookieMaxAgeSeconds(nowSec + 3600, 86400)).toBe(3600)
    expect(idTokenCookieMaxAgeSeconds(nowSec + 200000, 86400)).toBe(86400)
    expect(idTokenCookieMaxAgeSeconds(nowSec - 10, 86400)).toBe(1)
  })
})
