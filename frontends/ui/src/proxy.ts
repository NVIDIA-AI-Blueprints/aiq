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
  TOKEN_REFRESH_BUFFER_SECONDS,
  SESSION_MAX_AGE_SECONDS,
  isAuthRequired,
  shouldUseSecureCookies,
} from '@/adapters/auth/config'

/**
 * Check if a token is expired or about to expire (within buffer period).
 * Returns true if the token should be considered invalid.
 */
const isTokenExpiredOrExpiring = (expiresAt: number | undefined): boolean => {
  if (!expiresAt) return true
  const expiresAtWithBuffer = expiresAt - TOKEN_REFRESH_BUFFER_SECONDS
  return Date.now() >= expiresAtWithBuffer * 1000
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

      // Set idToken cookie only if we have a valid, non-expired token
      // If token is expired or expiring, don't set the cookie - this forces
      // the client-side session check to trigger a refresh via useSession()
      if (token.idToken && !isTokenExpiredOrExpiring(expiresAt)) {
        response.cookies.set('idToken', token.idToken as string, {
          httpOnly: true,
          sameSite: 'lax',
          path: '/',
          secure: shouldUseSecureCookies(),
          maxAge: SESSION_MAX_AGE_SECONDS,
        })
      } else if (isTokenExpiredOrExpiring(expiresAt)) {
        // Token is expired or about to expire - clear the cookie
        // This signals to the client that re-authentication or refresh is needed
        response.cookies.delete('idToken')
      } else {
        // No idToken in session - clear the cookie
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
