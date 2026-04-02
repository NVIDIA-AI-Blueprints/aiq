// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Next.js Proxy for Authentication Cookie Management
 *
 * This proxy extracts the idToken from the NextAuth JWT session and sets it
 * as a cookie on every request. The backend expects this cookie to identify users.
 *
 * IMPORTANT: Token refresh happens ONLY in NextAuth's JWT callback (config.ts),
 * not here. The proxy cannot update the NextAuth JWT session, and many OAuth
 * providers use rotating refresh tokens (each refresh invalidates the previous token).
 * If we refresh here, the new refresh_token would be lost and subsequent refreshes
 * would fail with "invalid_grant".
 *
 * The backend looks for user auth in priority order:
 * 1. Cookie: idToken (this proxy provides this)
 * 2. Env: Backend auth token
 * 3. Cached token from interactive login
 *
 * Note: In Next.js 16+, proxy.ts replaces middleware.ts and runs in Node.js
 * runtime by default, which provides full access to Node.js APIs.
 */

import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { getToken } from 'next-auth/jwt'
import {
  SESSION_MAX_AGE_SECONDS,
  isAuthRequired,
  shouldUseSecureCookies,
} from '@/adapters/auth/config'

/**
 * Check if a token is actually expired (real expiry, not refresh buffer).
 * The refresh buffer is for proactive token refresh in the NextAuth JWT
 * callback — the cookie should remain valid until the token truly expires
 * so that WebSocket and SSE transports can still authenticate.
 */
const isTokenExpired = (expiresAt: number | undefined): boolean => {
  if (!expiresAt) return true
  return Date.now() >= expiresAt * 1000
}

/**
 * Compute the cookie maxAge so it expires with the token rather than
 * lasting a fixed 24 hours. Clamped to [1, SESSION_MAX_AGE_SECONDS].
 */
const idTokenCookieMaxAgeSeconds = (expiresAt: number): number => {
  const nowSec = Math.floor(Date.now() / 1000)
  return Math.min(SESSION_MAX_AGE_SECONDS, Math.max(1, expiresAt - nowSec))
}

export default async function proxy(req: NextRequest) {
  if (!isAuthRequired()) {
    const response = NextResponse.next()
    response.cookies.delete('idToken')
    response.cookies.delete('next-auth.session-token')
    response.cookies.delete('__Secure-next-auth.session-token')
    response.cookies.delete('next-auth.csrf-token')
    response.cookies.delete('__Host-next-auth.csrf-token')
    response.cookies.delete('next-auth.callback-url')
    response.cookies.delete('__Secure-next-auth.callback-url')
    return response
  }

  // Skip proxy for static files and auth routes
  if (
    req.nextUrl.pathname.startsWith('/_next/') ||
    req.nextUrl.pathname.startsWith('/api/auth/') ||
    req.nextUrl.pathname.startsWith('/favicon.ico') ||
    req.nextUrl.pathname.startsWith('/public/')
  ) {
    return NextResponse.next()
  }

  const response = NextResponse.next()

  try {
    const token = await getToken({
      req,
      secret: process.env.NEXTAUTH_SECRET,
      secureCookie: shouldUseSecureCookies(),
    })

    if (token) {
      // Check for refresh error from NextAuth JWT callback
      if (token.error === 'RefreshAccessTokenError' || token.error === 'DevTokenExpired') {
        response.cookies.delete('idToken')
        return response
      }

      const expiresAt = token.expiresAt as number | undefined

      // Set idToken cookie only if we have a valid, non-expired token.
      // Unlike the refresh buffer (which proactively refreshes tokens),
      // the cookie stays valid until real expiry so WebSocket/SSE
      // transports don't lose auth while NextAuth refreshes in the background.
      if (token.idToken && !isTokenExpired(expiresAt)) {
        response.cookies.set('idToken', token.idToken as string, {
          httpOnly: true,
          sameSite: 'lax',
          path: '/',
          secure: shouldUseSecureCookies(),
          maxAge: idTokenCookieMaxAgeSeconds(expiresAt!),
        })
      } else {
        // Token expired or absent - clear the cookie
        response.cookies.delete('idToken')
      }
    } else {
      // No token - clear the idToken cookie
      response.cookies.delete('idToken')
    }
  } catch (error) {
    console.error('[Proxy] Error processing token:', error)
  }

  return response
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder
     *
     * Note: API auth routes are filtered dynamically in the proxy
     * function to allow NextAuth to handle them without interference
     */
    '/((?!_next/static|_next/image|favicon.ico|public).*)',
  ],
}
