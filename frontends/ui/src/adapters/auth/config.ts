// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Authentication Configuration
 *
 * NextAuth configuration with a generic OIDC provider scaffold.
 * By default, authentication is not required. Set REQUIRE_AUTH=true to enable.
 *
 * To enable authentication, configure the following environment variables:
 *   OAUTH_CLIENT_ID        - Your OIDC provider's client ID
 *   OAUTH_CLIENT_SECRET    - Your OIDC provider's client secret
 *   OAUTH_ISSUER           - OIDC issuer URL (enables auto-discovery via .well-known)
 *   OAUTH_AUTH_URL         - Authorization endpoint (fallback if no issuer)
 *   OAUTH_TOKEN_URL        - Token endpoint (fallback if no issuer)
 *   OAUTH_USERINFO_URL     - UserInfo endpoint (fallback if no issuer)
 *   NEXTAUTH_URL           - Your application's canonical URL
 *   NEXTAUTH_SECRET        - A random secret for signing tokens
 */

import { type AuthOptions, type Account, type User, type Session } from 'next-auth'
import { type JWT } from 'next-auth/jwt'
import CredentialsProvider from 'next-auth/providers/credentials'

// Import type extensions
import './types'

export const isAuthRequired = (): boolean => {
  return process.env.REQUIRE_AUTH === 'true'
}

/**
 * Determines if cookies should be set with the `secure` flag.
 *
 * Priority:
 * 1. Explicit SECURE_COOKIES env var (allows override for edge cases)
 * 2. NEXTAUTH_URL protocol (recommended: set NEXTAUTH_URL to match actual access URL)
 *
 * For reverse proxy setups (Nginx/Traefik/CloudFlare terminating TLS),
 * set NEXTAUTH_URL to the external HTTPS URL, not the internal HTTP URL.
 */
export const shouldUseSecureCookies = (): boolean => {
  const explicitSetting = process.env.SECURE_COOKIES
  if (explicitSetting !== undefined) {
    return explicitSetting === 'true'
  }

  const nextAuthUrl = process.env.NEXTAUTH_URL || ''
  return nextAuthUrl.startsWith('https://')
}

/**
 * Generic OIDC Provider configuration (example)
 *
 * Uncomment and configure the provider below to use your own OIDC-compatible
 * identity provider (e.g., Keycloak, Auth0, Okta, Azure AD, Google, etc.).
 *
 * Required env vars:
 *   OAUTH_CLIENT_ID        - Client ID from your OIDC provider
 *   OAUTH_CLIENT_SECRET    - Client secret from your OIDC provider
 *
 * Option A - Auto-discovery (recommended):
 *   OAUTH_ISSUER           - Issuer URL (e.g., https://accounts.google.com)
 *
 * Option B - Manual endpoints:
 *   OAUTH_AUTH_URL         - Authorization endpoint
 *   OAUTH_TOKEN_URL        - Token endpoint
 *   OAUTH_USERINFO_URL     - UserInfo endpoint
 */
// const OAuthProvider = {
//   id: 'oauth',
//   name: 'OAuth Provider',
//   type: 'oauth' as const,
//
//   // OIDC Discovery endpoint - auto-configures most settings
//   wellKnown: process.env.OAUTH_ISSUER
//     ? `${process.env.OAUTH_ISSUER}/.well-known/openid-configuration`
//     : undefined,
//
//   // Manual configuration (used when wellKnown is not available)
//   authorization: {
//     url: process.env.OAUTH_AUTH_URL,
//     params: {
//       scope: 'openid profile email',
//       response_type: 'code',
//     },
//   },
//
//   token: {
//     url: process.env.OAUTH_TOKEN_URL,
//   },
//   userinfo: {
//     url: process.env.OAUTH_USERINFO_URL,
//   },
//
//   clientId: process.env.OAUTH_CLIENT_ID,
//   clientSecret: process.env.OAUTH_CLIENT_SECRET || '',
//
//   checks: ['pkce', 'state'] as ('pkce' | 'state' | 'nonce')[],
//
//   idToken: true,
//
//   profile(profile: { sub: string; email: string; name: string; picture?: string }) {
//     return {
//       id: profile.sub,
//       email: profile.email,
//       name: profile.name,
//       image: profile.picture,
//     }
//   },
// }

/**
 * Buffer time before token expiry to trigger proactive refresh.
 * Refresh 5 minutes before expiry to prevent race conditions and
 * ensure tokens are always valid when used.
 */
export const TOKEN_REFRESH_BUFFER_SECONDS = 5 * 60

/**
 * NextAuth configuration options
 */
export const authOptions: AuthOptions = {
  secret: process.env.NEXTAUTH_SECRET || (!isAuthRequired() ? 'disabled-auth-secret' : undefined),

  providers: !isAuthRequired()
    ? [
        CredentialsProvider({
          id: 'disabled-auth',
          name: 'Disabled Auth',
          credentials: {},
          authorize: async () => null,
        }),
      ]
    : [
        // When auth is enabled (REQUIRE_AUTH=true), uncomment OAuthProvider above
        // and replace this empty array entry with: OAuthProvider
        // For now, no provider is configured -- the app will show an error on sign-in
        // until you configure your OIDC provider.
      ],

  session: {
    strategy: 'jwt',
    maxAge: 24 * 60 * 60, // 24 hours
  },

  pages: {
    signIn: '/auth/signin',
    error: '/auth/error',
  },

  callbacks: {
    async jwt({ token, account, user }: { token: JWT; account: Account | null; user?: User }) {
      // Initial sign in from OAuth provider
      if (account && user) {
        return {
          ...token,
          accessToken: account.access_token,
          idToken: account.id_token,
          refreshToken: account.refresh_token,
          expiresAt: account.expires_at,
          userId: user.id,
        }
      }

      // Return previous token if the access token has not expired yet (with buffer)
      const expiresAt = (token.expiresAt as number) || 0
      const expiresAtWithBuffer = expiresAt - TOKEN_REFRESH_BUFFER_SECONDS
      if (Date.now() < expiresAtWithBuffer * 1000) {
        return token
      }

      // Access token has expired, try to refresh it
      return refreshAccessToken(token)
    },

    async session({ session, token }: { session: Session; token: JWT }) {
      return {
        ...session,
        accessToken: token.accessToken as string | undefined,
        idToken: token.idToken as string | undefined,
        userId: token.userId as string | undefined,
        error: token.error as string | undefined,
      }
    },
  },

  events: {
    async signOut() {
      // Clean up any cached tokens
    },
  },

  debug: process.env.NODE_ENV === 'development',
}

/**
 * Refresh the access token using the refresh token.
 * Requires OAUTH_TOKEN_URL and OAUTH_CLIENT_ID to be set.
 */
const refreshAccessToken = async (token: JWT): Promise<JWT> => {
  try {
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
        refresh_token: token.refreshToken as string,
        client_id: process.env.OAUTH_CLIENT_ID || '',
      }),
    })

    const refreshedTokens = await response.json()

    if (!response.ok) {
      throw refreshedTokens
    }

    return {
      ...token,
      accessToken: refreshedTokens.access_token,
      idToken: refreshedTokens.id_token ?? token.idToken,
      expiresAt: Math.floor(Date.now() / 1000) + refreshedTokens.expires_in,
      refreshToken: refreshedTokens.refresh_token ?? token.refreshToken,
    }
  } catch (error) {
    console.error('Error refreshing access token:', error)

    return {
      ...token,
      error: 'RefreshAccessTokenError',
    }
  }
}

/**
 * Environment variable validation for auth
 */
export const validateAuthEnv = (): { isValid: boolean; missing: string[] } => {
  if (!isAuthRequired()) {
    return { isValid: true, missing: [] }
  }

  const required = ['NEXTAUTH_URL', 'NEXTAUTH_SECRET']

  const missing: string[] = []

  for (const key of required) {
    if (!process.env[key]) {
      missing.push(key)
    }
  }

  // Client ID is required for OAuth to work
  if (!process.env.OAUTH_CLIENT_ID) {
    missing.push('OAUTH_CLIENT_ID')
  }

  return {
    isValid: missing.length === 0,
    missing,
  }
}
