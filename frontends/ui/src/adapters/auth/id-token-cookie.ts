// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const TOKEN_REFRESH_ERROR_CODES = new Set(['RefreshAccessTokenError', 'DevTokenExpired'])

export type IdTokenCookieDecision = 'set' | 'delete' | 'preserve'

interface IdTokenCookieDecisionInput {
  tokenError?: unknown
  idToken?: unknown
  expiresAt?: number
  preserveExpiredRequestToken?: boolean
}

/**
 * Check if a token is actually expired (real expiry, not refresh buffer).
 * The refresh buffer is for proactive token refresh in the NextAuth JWT
 * callback; transport auth should remain usable until real token expiry.
 */
export const isTokenExpired = (expiresAt: number | undefined): boolean => {
  if (expiresAt === undefined) return true
  return Date.now() >= expiresAt * 1000
}

/**
 * Compute the cookie maxAge so it expires with the token rather than lasting a
 * fixed session lifetime. Clamped to [1, sessionMaxAgeSeconds].
 */
export const idTokenCookieMaxAgeSeconds = (
  expiresAt: number,
  sessionMaxAgeSeconds: number
): number => {
  const nowSec = Math.floor(Date.now() / 1000)
  return Math.min(sessionMaxAgeSeconds, Math.max(1, expiresAt - nowSec))
}

export const getIdTokenCookieDecision = ({
  tokenError,
  idToken,
  expiresAt,
  preserveExpiredRequestToken = false,
}: IdTokenCookieDecisionInput): IdTokenCookieDecision => {
  if (typeof tokenError === 'string' && TOKEN_REFRESH_ERROR_CODES.has(tokenError)) {
    return 'delete'
  }

  if (typeof idToken !== 'string' || idToken.length === 0) {
    return 'delete'
  }

  if (expiresAt === undefined) {
    return 'delete'
  }

  if (isTokenExpired(expiresAt)) {
    return preserveExpiredRequestToken ? 'preserve' : 'delete'
  }

  return 'set'
}
