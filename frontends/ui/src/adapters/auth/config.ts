// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Authentication Configuration
 *
 * NextAuth configuration with pluggable auth providers.
 *
 * Provider selection (AUTH_PROVIDER env var):
 *   - 'generic' (default) — Generic OIDC provider using OAUTH_* env vars
 *   - 'internalauth'       — Internal OIDC provider using INTERNAL_AUTH_* env vars
 *
 * When REQUIRE_AUTH=false (default), authentication is disabled entirely.
 */

import { type AuthOptions, type Account, type User, type Session } from 'next-auth'
import { type JWT } from 'next-auth/jwt'
import CredentialsProvider from 'next-auth/providers/credentials'

import {
  InternalAuthProvider,
  getInternalAuthClientId,
  getInternalAuthProviderId,
  refreshInternalAuthToken,
  GenericOIDCProvider,
  refreshGenericToken,
} from './providers'

// Import type extensions
import './types'

// ---------------------------------------------------------------------------
// Auth provider selection
// ---------------------------------------------------------------------------

export const AUTH_PROVIDER = (process.env.AUTH_PROVIDER || 'generic').toLowerCase()

/**
 * The NextAuth provider ID used for signIn() calls.
 * InternalAuth ID is configurable for compatibility with legacy callback paths.
 */
export const AUTH_PROVIDER_ID =
  AUTH_PROVIDER === 'internalauth' ? getInternalAuthProviderId() : 'oauth'

const getAuthProvider = () => {
  if (AUTH_PROVIDER === 'internalauth') return InternalAuthProvider
  return GenericOIDCProvider
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
 * Default: 5 minutes for generic, 30 minutes recommended for ECI deployments
 * (deep research jobs can run 20-40+ minutes).
 *
 * Override via TOKEN_REFRESH_BUFFER_MINUTES env var.
 */
export const TOKEN_REFRESH_BUFFER_SECONDS =
  parseInt(process.env.TOKEN_REFRESH_BUFFER_MINUTES || '5', 10) * 60

/**
 * Max age (seconds) for the idToken cookie.
 * Default: 720 hours (30 days). Set to 24 for enterprise/InternalAuth deployments.
 *
 * Override via ID_TOKEN_COOKIE_HOURS env var.
 */
export const ID_TOKEN_COOKIE_MAX_AGE =
  parseInt(process.env.ID_TOKEN_COOKIE_HOURS || '720', 10) * 60 * 60

// ---------------------------------------------------------------------------
// LDAP-API gating — no-op when env vars are absent
// ---------------------------------------------------------------------------

const isLdapGatingConfigured = (): boolean => {
  return !!(
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
// Token refresh (provider-aware)
// ---------------------------------------------------------------------------

const refreshAccessToken = async (token: JWT): Promise<JWT> => {
  try {
    const refreshed =
      AUTH_PROVIDER === 'internalauth'
        ? await refreshInternalAuthToken(token.refreshToken as string)
        : await refreshGenericToken(token.refreshToken as string)

    return {
      ...token,
      accessToken: refreshed.access_token,
      idToken: refreshed.id_token ?? token.idToken,
      expiresAt: Math.floor(Date.now() / 1000) + refreshed.expires_in,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
    }
  } catch (error) {
    console.error('[Auth] Token refresh failed:', error)
    return {
      ...token,
      error: 'RefreshAccessTokenError',
    }
  }
}

// ---------------------------------------------------------------------------
// NextAuth configuration
// ---------------------------------------------------------------------------

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
    : [getAuthProvider()],

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
      if (account && user) {
        const hasAccess = user.email ? await checkUserAccess(user.email) : true

        return {
          ...token,
          accessToken: account.access_token,
          idToken: account.id_token,
          refreshToken: account.refresh_token,
          expiresAt: account.expires_at,
          userId: user.id,
          hasAccess,
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

  const required = ['NEXTAUTH_URL', 'NEXTAUTH_SECRET']
  const missing: string[] = []

  for (const key of required) {
    if (!process.env[key]) {
      missing.push(key)
    }
  }

  if (AUTH_PROVIDER === 'internalauth') {
    if (!getInternalAuthClientId()) {
      missing.push('INTERNAL_AUTH_CLIENT_ID (or INTERNAL_AUTH_CLIENT_ID_BROWSER)')
    }
  } else {
    if (!process.env.OAUTH_CLIENT_ID) {
      missing.push('OAUTH_CLIENT_ID')
    }
  }

  return {
    isValid: missing.length === 0,
    missing,
  }
}
