// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Authentication Configuration
 *
 * NextAuth configuration with pluggable auth provider architecture.
 *
 * Authentication is DISABLED by default. The app runs with a default user
 * and no login is required (REQUIRE_AUTH=false).
 *
 * Auth providers have been removed from this repository. To enable auth,
 * implement a provider in ./providers/ and wire it into this file.
 * See ./providers/internal-auth.ts for a complete (commented-out) reference.
 *
 * If REQUIRE_AUTH=true is set without an active provider, a console warning
 * is logged and the app falls through to default user.
 */

import { type AuthOptions, type Account, type User, type Session } from 'next-auth'
import { type JWT } from 'next-auth/jwt'
import CredentialsProvider from 'next-auth/providers/credentials'

// Import type extensions
import './types'

// ---------------------------------------------------------------------------
// Auth provider selection
// ---------------------------------------------------------------------------

export const AUTH_PROVIDER = (process.env.AUTH_PROVIDER || 'generic').toLowerCase()

/**
 * The NextAuth provider ID used for signIn() calls.
 * When no provider is active this is 'disabled-auth'.
 *
 * When re-enabling a provider, set this to the provider's ID
 * (e.g. getInternalAuthProviderId() for InternalAuth).
 */
export const AUTH_PROVIDER_ID = 'disabled-auth'

// No auth providers are currently enabled. To enable a provider,
// uncomment and wire the provider in ./providers/ and restore the
// import + dispatch here. See ./providers/internal-auth.ts for reference.
const getAuthProvider = (): null => {
  return null
}

// Log once at module load if REQUIRE_AUTH=true but no provider is available
if (process.env.REQUIRE_AUTH?.toLowerCase() === 'true') {
  console.warn(
    '[Auth] REQUIRE_AUTH=true but no auth provider is configured. ' +
      'Falling through to default user. ' +
      'See src/adapters/auth/providers/ to enable a provider.'
  )
}

// ---------------------------------------------------------------------------
// Core helpers
// ---------------------------------------------------------------------------

export const isAuthRequired = (): boolean => {
  return process.env.REQUIRE_AUTH?.toLowerCase() === 'true'
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

// ---------------------------------------------------------------------------
// Configurable token/cookie lifetimes
// ---------------------------------------------------------------------------

/**
 * Buffer time (seconds) before token expiry to trigger proactive refresh.
 * Default: 30 minutes (deep research jobs can run 20-40+ minutes).
 *
 * Override via TOKEN_REFRESH_BUFFER_MINUTES env var.
 */
export const TOKEN_REFRESH_BUFFER_SECONDS =
  parseInt(process.env.TOKEN_REFRESH_BUFFER_MINUTES || '30', 10) * 60

/**
 * Max age (seconds) for the idToken cookie.
 * Default: 24 hours. Must stay aligned with session.maxAge below.
 *
 * Override via ID_TOKEN_COOKIE_HOURS env var.
 */
export const ID_TOKEN_COOKIE_MAX_AGE =
  parseInt(process.env.ID_TOKEN_COOKIE_HOURS || '24', 10) * 60 * 60

// ---------------------------------------------------------------------------
// LDAP-API gating — no-op when env vars are absent or provider is not internalauth
// ---------------------------------------------------------------------------

const isLdapGatingConfigured = (): boolean => {
  return !!(
    AUTH_PROVIDER === 'internalauth' &&
    process.env.INTERNAL_AUTH_SSA_CLIENT_ID &&
    process.env.INTERNAL_AUTH_SSA_SECRET &&
    process.env.LDAP_API_SSA_TOKEN_ENDPOINT &&
    process.env.LDAP_GROUP &&
    process.env.LDAP_API_GROUPS_ENDPOINT
  )
}

const getLdapApiJwtToken = async (): Promise<string | null> => {
  const clientId = process.env.INTERNAL_AUTH_SSA_CLIENT_ID
  const clientSecret = process.env.INTERNAL_AUTH_SSA_SECRET
  const tokenEndpoint = process.env.LDAP_API_SSA_TOKEN_ENDPOINT

  if (!clientId || !clientSecret || !tokenEndpoint) {
    return null
  }

  try {
    const basicAuth = Buffer.from(`${clientId}:${clientSecret}`).toString('base64')

    const response = await fetch(tokenEndpoint, {
      method: 'POST',
      headers: {
        Authorization: `Basic ${basicAuth}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'client_credentials',
        scope: 'full-api',
      }),
    })

    if (!response.ok) {
      console.error(`[Auth/LDAP] SSA token request failed: ${response.status}`)
      return null
    }

    const tokenData = await response.json()
    return tokenData.access_token as string
  } catch (error) {
    console.error('[Auth/LDAP] Error obtaining SSA token:', error)
    return null
  }
}

/**
 * Check LDAP group membership via the configured LDAP-API.
 * Returns true (grant access) if LDAP gating is not configured or auth is not required.
 */
const checkUserAccess = async (userEmail: string): Promise<boolean> => {
  if (!isAuthRequired() || !isLdapGatingConfigured()) {
    return true
  }

  const ldapGroup = process.env.LDAP_GROUP!
  const userName = userEmail.split('@')[0] || userEmail
  const ldapApiGroupsEndpoint = process.env.LDAP_API_GROUPS_ENDPOINT

  try {
    const ldapApiToken = await getLdapApiJwtToken()
    if (!ldapApiToken) {
      console.error('[Auth/LDAP] Failed to obtain LDAP-API token, denying access')
      return false
    }

    if (!ldapApiGroupsEndpoint) {
      console.error('[Auth/LDAP] LDAP_API_GROUPS_ENDPOINT is not set, denying access')
      return false
    }

    const ldapApiUrl =
      `${ldapApiGroupsEndpoint}` +
      `?filter[descendantUserLogin]=${encodeURIComponent(userName)}` +
      `&filter[names]=${encodeURIComponent(ldapGroup)}`

    const response = await fetch(ldapApiUrl, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${ldapApiToken}`,
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      console.error(`[Auth/LDAP] LDAP-API request failed: ${response.status}`)
      return false
    }

    const data = await response.json()
    const hasAccess = Array.isArray(data.data) && data.data.length > 0

    console.log(
      `[Auth/LDAP] Access check for ${userName}: ${hasAccess ? 'granted' : 'denied'} (group: ${ldapGroup})`
    )
    return hasAccess
  } catch (error) {
    console.error('[Auth/LDAP] Error checking user access:', error)
    return false
  }
}

// ---------------------------------------------------------------------------
// Token refresh
// ---------------------------------------------------------------------------

/**
 * Token refresh stub. No provider is currently active, so this should never
 * be called. If it is, something is misconfigured — return an error token
 * so the session hook triggers re-auth.
 *
 * When re-enabling a provider, restore the provider-dispatched refresh logic
 * (see git history or ./providers/internal-auth.ts for reference).
 */
const refreshAccessToken = async (token: JWT): Promise<JWT> => {
  console.error('[Auth] Token refresh called but no auth provider is configured')
  return {
    ...token,
    error: 'RefreshAccessTokenError',
  }
}

// ---------------------------------------------------------------------------
// NextAuth configuration
// ---------------------------------------------------------------------------

const activeProvider = getAuthProvider()

export const authOptions: AuthOptions = {
  secret: process.env.NEXTAUTH_SECRET || (!isAuthRequired() || !activeProvider ? 'disabled-auth-secret' : undefined),

  providers: [
    CredentialsProvider({
      id: 'disabled-auth',
      name: 'Disabled Auth',
      credentials: {},
      authorize: async () => null,
    }),
  ],

  session: {
    strategy: 'jwt',
    maxAge: ID_TOKEN_COOKIE_MAX_AGE,
  },

  pages: {
    signIn: '/auth/signin',
    error: '/auth/error',
  },

  callbacks: {
    async signIn({ user }: { user: User }) {
      if (!isAuthRequired() || !isLdapGatingConfigured()) return true

      const hasAccess = user.email ? await checkUserAccess(user.email) : false
      if (!hasAccess) {
        const group = encodeURIComponent(process.env.LDAP_GROUP || '')
        return `/auth/signin?error=DLAccessDenied&dl_group=${group}`
      }
      return true
    },

    async jwt({ token, account, user }: { token: JWT; account: Account | null; user?: User }) {
      if (account && user) {
        return {
          ...token,
          accessToken: account.access_token,
          idToken: account.id_token,
          refreshToken: account.refresh_token,
          expiresAt: account.expires_at,
          userId: user.id,
          hasAccess: true,
          dlGroup: process.env.LDAP_GROUP,
        }
      }

      const expiresAt = (token.expiresAt as number) || 0
      const expiresAtWithBuffer = expiresAt - TOKEN_REFRESH_BUFFER_SECONDS
      if (Date.now() < expiresAtWithBuffer * 1000) {
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
        hasAccess: token.hasAccess as boolean | undefined,
        dlGroup: token.dlGroup as string | undefined,
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

  // No provider is active — warn but don't block
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
