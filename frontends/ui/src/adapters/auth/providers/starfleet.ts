// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * NVIDIA Starfleet SSO Provider
 *
 * OAuth provider for NVIDIA's internal Starfleet SSO (login.nvidia.com).
 * Activated when AUTH_PROVIDER=starfleet.
 *
 * Required env vars:
 *   AIQ_STARFLEET_CLIENT_ID or AIQ_STARFLEET_CLIENT_ID_BROWSER
 *   AIQ_STARFLEET_CLIENT_SECRET
 *   AIQ_STARFLEET_ISSUER (defaults to https://login.nvidia.com)
 *
 * Optional env vars for manual endpoint configuration:
 *   AIQ_STARFLEET_AUTH_URL
 *   AIQ_STARFLEET_TOKEN_URL
 *   AIQ_STARFLEET_USERINFO_URL
 */

import { type Profile } from 'next-auth'

export const getStarfleetClientId = (): string | undefined => {
  return process.env.AIQ_STARFLEET_CLIENT_ID || process.env.AIQ_STARFLEET_CLIENT_ID_BROWSER
}

export const StarfleetProvider = {
  id: 'nvlogin',
  name: 'NVIDIA SSO',
  type: 'oauth' as const,

  wellKnown: process.env.AIQ_STARFLEET_ISSUER
    ? `${process.env.AIQ_STARFLEET_ISSUER}/.well-known/openid-configuration`
    : undefined,

  authorization: {
    url: process.env.AIQ_STARFLEET_AUTH_URL || 'https://login.nvidia.com/authorize',
    params: {
      scope: 'openid profile email',
      response_type: 'code',
      code_challenge_method: 'S256',
    },
  },

  token: {
    url: process.env.AIQ_STARFLEET_TOKEN_URL || 'https://login.nvidia.com/token',
  },
  userinfo: {
    url: process.env.AIQ_STARFLEET_USERINFO_URL || 'https://login.nvidia.com/userinfo',
  },

  clientId: getStarfleetClientId(),
  clientSecret: process.env.AIQ_STARFLEET_CLIENT_SECRET || '',

  checks: ['pkce', 'state'] as ('pkce' | 'state' | 'nonce')[],

  // NVIDIA uses ES256 (Elliptic Curve) for signing ID tokens
  client: {
    id_token_signed_response_alg: 'ES256',
  },

  idToken: true,

  profile(profile: Profile & { sub: string; email: string; name: string; picture?: string }) {
    return {
      id: profile.sub,
      email: profile.email,
      name: profile.name,
      image: profile.picture,
    }
  },
}

/**
 * Refresh the access token using the Starfleet token endpoint.
 * Retries once after a short delay to handle transient network errors.
 * Bails immediately on invalid_grant (revoked refresh token).
 */
export const refreshStarfleetToken = async (
  refreshToken: string
): Promise<{
  access_token: string
  id_token?: string
  expires_in: number
  refresh_token?: string
}> => {
  const tokenUrl = process.env.AIQ_STARFLEET_TOKEN_URL || 'https://login.nvidia.com/token'
  const maxAttempts = 2
  let lastError: unknown

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(tokenUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({
          grant_type: 'refresh_token',
          refresh_token: refreshToken,
          client_id: getStarfleetClientId() || '',
        }),
      })

      const refreshedTokens = await response.json()

      if (!response.ok) {
        if (refreshedTokens.error === 'invalid_grant') {
          console.error('[Auth] Refresh token revoked (invalid_grant)')
          throw refreshedTokens
        }
        throw refreshedTokens
      }

      return refreshedTokens
    } catch (error) {
      lastError = error
      if (attempt < maxAttempts) {
        console.warn(`[Auth] Token refresh attempt ${attempt} failed, retrying...`)
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
    }
  }

  throw lastError
}
