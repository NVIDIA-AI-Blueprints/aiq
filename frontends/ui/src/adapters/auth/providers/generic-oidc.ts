// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Generic OIDC Provider
 *
 * Works with any OIDC-compatible identity provider (Keycloak, Auth0, Okta,
 * Azure AD, Google, etc.). Activated when AUTH_PROVIDER is unset or 'generic'.
 *
 * Required env vars:
 *   OAUTH_CLIENT_ID
 *   OAUTH_CLIENT_SECRET
 *
 * Option A - Auto-discovery (recommended):
 *   OAUTH_ISSUER  (e.g., https://accounts.google.com)
 *
 * Option B - Manual endpoints:
 *   OAUTH_AUTH_URL
 *   OAUTH_TOKEN_URL
 *   OAUTH_USERINFO_URL
 */

export const GenericOIDCProvider = {
  id: 'oauth',
  name: 'OAuth Provider',
  type: 'oauth' as const,

  wellKnown: process.env.OAUTH_ISSUER
    ? `${process.env.OAUTH_ISSUER}/.well-known/openid-configuration`
    : undefined,

  authorization: {
    url: process.env.OAUTH_AUTH_URL,
    params: {
      scope: 'openid profile email',
      response_type: 'code',
    },
  },

  token: {
    url: process.env.OAUTH_TOKEN_URL,
  },
  userinfo: {
    url: process.env.OAUTH_USERINFO_URL,
  },

  clientId: process.env.OAUTH_CLIENT_ID,
  clientSecret: process.env.OAUTH_CLIENT_SECRET || '',

  checks: ['pkce', 'state'] as ('pkce' | 'state' | 'nonce')[],

  idToken: true,

  profile(profile: { sub: string; email: string; name: string; picture?: string }) {
    return {
      id: profile.sub,
      email: profile.email,
      name: profile.name,
      image: profile.picture,
    }
  },
}

/**
 * Refresh the access token using the generic OIDC token endpoint.
 */
export const refreshGenericToken = async (
  refreshToken: string
): Promise<{
  access_token: string
  id_token?: string
  expires_in: number
  refresh_token?: string
}> => {
  const tokenUrl = process.env.OAUTH_TOKEN_URL
  if (!tokenUrl) {
    throw new Error('OAUTH_TOKEN_URL is not configured')
  }

  const response = await fetch(tokenUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: refreshToken,
      client_id: process.env.OAUTH_CLIENT_ID || '',
    }),
  })

  const refreshedTokens = await response.json()

  if (!response.ok) {
    throw refreshedTokens
  }

  return refreshedTokens
}
