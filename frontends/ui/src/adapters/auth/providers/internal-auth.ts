// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * InternalAuth OIDC Provider
 *
 * OAuth provider for private/internal identity providers.
 * Activated when AUTH_PROVIDER=internalauth.
 *
 * Required env vars:
 *   INTERNAL_AUTH_CLIENT_ID or INTERNAL_AUTH_CLIENT_ID_BROWSER
 *   INTERNAL_AUTH_CLIENT_SECRET
 *
 * Recommended env vars:
 *   INTERNAL_AUTH_ISSUER
 *
 * Optional env vars for manual endpoint configuration:
 *   INTERNAL_AUTH_AUTH_URL
 *   INTERNAL_AUTH_TOKEN_URL
 *   INTERNAL_AUTH_USERINFO_URL
 */

import { type Profile } from 'next-auth'

export const getInternalAuthClientId = (): string | undefined => {
  // Prefer browser client for NextAuth web sign-in flows; fallback to generic/client ID.
  return process.env.INTERNAL_AUTH_CLIENT_ID_BROWSER || process.env.INTERNAL_AUTH_CLIENT_ID
}

export const getInternalAuthProviderId = (): string => {
  return process.env.INTERNAL_AUTH_PROVIDER_ID || 'internalauth'
}

const issuer = process.env.INTERNAL_AUTH_ISSUER

export const InternalAuthProvider = {
  id: getInternalAuthProviderId(),
  name: 'InternalAuth',
  type: 'oauth' as const,

  wellKnown: issuer ? `${issuer}/.well-known/openid-configuration` : undefined,

  authorization: {
    url: process.env.INTERNAL_AUTH_AUTH_URL || (issuer ? `${issuer}/authorize` : ''),
    params: {
      scope: 'openid profile email',
      response_type: 'code',
      code_challenge_method: 'S256',
    },
  },

  token: {
    url: process.env.INTERNAL_AUTH_TOKEN_URL || (issuer ? `${issuer}/token` : ''),
  },
  userinfo: {
    url: process.env.INTERNAL_AUTH_USERINFO_URL || (issuer ? `${issuer}/userinfo` : ''),
  },

  clientId: getInternalAuthClientId(),
  clientSecret: process.env.INTERNAL_AUTH_CLIENT_SECRET || '',

  checks: ['pkce', 'state'] as ('pkce' | 'state' | 'nonce')[],

  // Keep ES256 because many internal IdPs issue ES256-signed ID tokens.
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
 * Refresh the access token using the InternalAuth token endpoint.
 * Retries once after a short delay to handle transient network errors.
 * Bails immediately on invalid_grant (revoked refresh token).
 */
export const refreshInternalAuthToken = async (
  refreshToken: string
): Promise<{
  access_token: string
  id_token?: string
  expires_in: number
  refresh_token?: string
}> => {
  const tokenUrl = process.env.INTERNAL_AUTH_TOKEN_URL || (issuer ? `${issuer}/token` : '')
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
          client_id: getInternalAuthClientId() || '',
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
