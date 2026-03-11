// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Authentication Configuration
 *
 * NextAuth configuration with pluggable auth provider architecture.
 * The active provider is determined by ./providers/index.ts (the sole swap-point).
 *
 * By default, no provider is active and authentication is disabled.
 * Set REQUIRE_AUTH=true and configure a provider to enable OAuth.
 *
 * See ./providers/auth-example.ts for a provider template
 * and ./providers/types.ts for the provider contract.
 */

import 'server-only'
import { randomUUID } from 'node:crypto'
import { type AuthOptions, type Account, type User, type Session } from 'next-auth'
import { type JWT } from 'next-auth/jwt'
import CredentialsProvider from 'next-auth/providers/credentials'
import { getAuthProviderConfig } from './providers'

// Import type extensions
import './types'

// ---------------------------------------------------------------------------
// Auth provider (from providers/index.ts)
// ---------------------------------------------------------------------------

const {
  provider: activeProvider,
  providerId,
  refreshToken: refreshProviderToken,
} = getAuthProviderConfig()

/**
 * The NextAuth provider ID used for signIn() calls.
 * Derived from the active provider, or 'disabled-auth' when no provider is configured.
 */
export const AUTH_PROVIDER_ID = activeProvider ? providerId : 'disabled-auth'

// ---------------------------------------------------------------------------
// Core helpers
// ---------------------------------------------------------------------------

export const isAuthRequired = (): boolean => {
  return process.env.REQUIRE_AUTH?.toLowerCase() === 'true'
}

if (isAuthRequired() && !activeProvider) {
  console.warn(
    '[Auth] REQUIRE_AUTH=true but no auth provider is configured. ' +
      'Falling through to default user. ' +
      'See src/adapters/auth/providers/ to enable a provider.'
  )
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

const parsePositiveIntEnv = (envValue: string | undefined, defaultValue: number): number => {
  if (envValue === undefined) return defaultValue

  const parsed = Number.parseInt(envValue, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue
}

// ---------------------------------------------------------------------------
// Configurable token/cookie lifetimes
// ---------------------------------------------------------------------------

/**
 * Buffer time (seconds) before token expiry to trigger proactive refresh.
 * Default: 5 minutes. For deployments with long-running jobs (deep research
 * can run 20-40+ minutes), set TOKEN_REFRESH_BUFFER_MINUTES=30.
 *
 * Override via TOKEN_REFRESH_BUFFER_MINUTES env var.
 */
export const TOKEN_REFRESH_BUFFER_SECONDS =
  parsePositiveIntEnv(process.env.TOKEN_REFRESH_BUFFER_MINUTES, 5) * 60

/**
 * Max age (seconds) for both the NextAuth session and the idToken cookie.
 * These MUST stay aligned -- a session that outlives its cookie (or vice versa)
 * causes stale-credential or premature-logout bugs.
 *
 * Default: 24 hours. Override via SESSION_MAX_AGE_HOURS env var.
 */
export const SESSION_MAX_AGE_SECONDS =
  parsePositiveIntEnv(process.env.SESSION_MAX_AGE_HOURS, 24) * 60 * 60

// ---------------------------------------------------------------------------
// Token refresh (delegates to active provider)
// ---------------------------------------------------------------------------

const refreshAccessToken = async (token: JWT): Promise<JWT> => {
  if (!activeProvider) {
    console.error('[Auth] Token refresh called but no auth provider is configured')
    return { ...token, error: 'RefreshAccessTokenError' }
  }

  try {
    const refreshed = await refreshProviderToken(token.refreshToken as string)

    return {
      ...token,
      accessToken: refreshed.access_token,
      idToken: refreshed.id_token ?? token.idToken,
      expiresAt: Math.floor(Date.now() / 1000) + refreshed.expires_in,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
    }
  } catch (error) {
    console.error('[Auth] Token refresh failed:', error)
    return { ...token, error: 'RefreshAccessTokenError' }
  }
}

// ---------------------------------------------------------------------------
// NextAuth configuration
// ---------------------------------------------------------------------------

export const authOptions: AuthOptions = {
  secret: process.env.NEXTAUTH_SECRET || (!isAuthRequired() || !activeProvider ? randomUUID() : undefined),

  providers: (
    !isAuthRequired() || !activeProvider
      ? [
          CredentialsProvider({
            id: 'disabled-auth',
            name: 'Disabled Auth',
            credentials: {},
            authorize: async () => null,
          }),
        ]
      : [activeProvider]
  ) as AuthOptions['providers'],

  session: {
    strategy: 'jwt',
    maxAge: SESSION_MAX_AGE_SECONDS,
  },

  pages: {
    signIn: '/auth/signin',
    error: '/auth/error',
  },

  callbacks: {
    async jwt({ token, account, user }: { token: JWT; account: Account | null; user?: User }) {
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

      const expiresAt = token.expiresAt as number | undefined

      if (expiresAt !== undefined) {
        const expiresAtWithBuffer = expiresAt - TOKEN_REFRESH_BUFFER_SECONDS
        if (Date.now() < expiresAtWithBuffer * 1000) {
          return token
        }
      } else {
        // Some providers do not return expires_at. In that case we cannot
        // safely schedule proactive refreshes, but refreshing on every session
        // check will churn rotating refresh tokens. Keep the current token and
        // rely on providers that support refresh to populate expiresAt.
        return token
      }

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

// ---------------------------------------------------------------------------
// Environment validation
// ---------------------------------------------------------------------------

export const validateAuthEnv = (): { isValid: boolean; missing: string[] } => {
  if (!isAuthRequired()) {
    return { isValid: true, missing: [] }
  }

  if (!activeProvider) {
    console.warn('[Auth] REQUIRE_AUTH=true but no auth provider is active. Auth will be bypassed.')
    return { isValid: true, missing: [] }
  }

  const required = ['NEXTAUTH_URL', 'NEXTAUTH_SECRET']
  const missing: string[] = []

  for (const key of required) {
    if (!process.env[key]) {
      missing.push(key)
    }
  }

  return {
    isValid: missing.length === 0,
    missing,
  }
}
