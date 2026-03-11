// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * NextAuth API Route Handler
 *
 * Handles all authentication requests:
 * - GET /api/auth/signin
 * - GET /api/auth/signout
 * - GET /api/auth/session
 * - POST /api/auth/callback/oauth
 *
 * After successful OAuth callback, sets the idToken as a cookie for backend auth.
 * This is necessary because middleware skips /api/auth/ routes.
 */

import { NextRequest, NextResponse } from 'next/server'
import NextAuth from 'next-auth'
import { getToken } from 'next-auth/jwt'
import {
  authOptions,
  isAuthRequired,
  SESSION_MAX_AGE_SECONDS,
  shouldUseSecureCookies,
} from '@/adapters/auth/config'

const nextAuthHandler = NextAuth(authOptions)

const clearAuthCookies = (response: NextResponse): void => {
  response.cookies.delete('idToken')
  response.cookies.delete('next-auth.session-token')
  response.cookies.delete('__Secure-next-auth.session-token')
  response.cookies.delete('next-auth.csrf-token')
  response.cookies.delete('__Host-next-auth.csrf-token')
  response.cookies.delete('next-auth.callback-url')
  response.cookies.delete('__Secure-next-auth.callback-url')
}

/**
 * Wrapper that sets idToken cookie after successful auth callback.
 * The middleware skips /api/auth/ routes, so we need to set the cookie here.
 *
 * Handles both:
 * - OAuth callbacks (GET /api/auth/callback/oauth)
 * - Credentials callbacks (POST /api/auth/callback/dev-bypass)
 */
const withIdTokenCookie = async (
  req: NextRequest,
  context: { params: Promise<{ nextauth: string[] }> }
): Promise<Response> => {
  const params = await context.params

  if (!isAuthRequired()) {
    const action = params.nextauth?.[0]

    if (action === 'session') {
      const response = NextResponse.json({}, { status: 200 })
      clearAuthCookies(response)
      return response
    }

    const response = NextResponse.json({ ok: true }, { status: 200 })
    clearAuthCookies(response)
    return response
  }

  // Run NextAuth handler first
  const response = await nextAuthHandler(req, context)

  // Check if this is a callback (OAuth GET or Credentials POST)
  const isCallback = params.nextauth?.includes('callback')

  if (isCallback) {
    try {
      const token = await getToken({
        req,
        secret: process.env.NEXTAUTH_SECRET,
      })

      if (token?.idToken) {
        console.log('[NextAuth] Setting idToken cookie after callback')

        // Clone the response to modify headers
        const newResponse = new NextResponse(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers: new Headers(response.headers),
        })

        // Keep callback-set cookies aligned with the shared auth session lifetime.
        newResponse.cookies.set('idToken', token.idToken as string, {
          httpOnly: true,
          sameSite: 'lax',
          path: '/',
          secure: shouldUseSecureCookies(),
          maxAge: SESSION_MAX_AGE_SECONDS,
        })

        return newResponse
      }
    } catch (error) {
      console.error('[NextAuth] Error setting idToken cookie:', error)
    }
  }

  return response
}

export const GET = withIdTokenCookie
export const POST = withIdTokenCookie
