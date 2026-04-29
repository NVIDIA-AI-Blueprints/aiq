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

const isTokenExpired = (expiresAt: number | undefined): boolean => {
  if (!expiresAt) return true
  return Date.now() >= expiresAt * 1000
}

const idTokenCookieMaxAgeSeconds = (expiresAt: number): number => {
  const nowSec = Math.floor(Date.now() / 1000)
  return Math.min(SESSION_MAX_AGE_SECONDS, Math.max(1, expiresAt - nowSec))
}

const cloneResponse = (response: Response): NextResponse =>
  new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: new Headers(response.headers),
  })

const syncIdTokenCookie = async (
  req: NextRequest,
  response: Response
): Promise<NextResponse> => {
  const newResponse = cloneResponse(response)

  try {
    const token = await getToken({
      req,
      secret: process.env.NEXTAUTH_SECRET,
      secureCookie: shouldUseSecureCookies(),
    })

    const expiresAt = token?.expiresAt as number | undefined
    if (token?.error === 'RefreshAccessTokenError' || !token?.idToken || isTokenExpired(expiresAt)) {
      newResponse.cookies.delete('idToken')
      return newResponse
    }

    newResponse.cookies.set('idToken', token.idToken as string, {
      httpOnly: true,
      sameSite: 'lax',
      path: '/',
      secure: shouldUseSecureCookies(),
      maxAge: idTokenCookieMaxAgeSeconds(expiresAt!),
    })
  } catch (error) {
    console.error('[NextAuth] Error syncing idToken cookie:', error)
  }

  return newResponse
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
  const action = params.nextauth?.[0]

  // Check if this is a callback (OAuth GET or Credentials POST)
  const isCallback = params.nextauth?.includes('callback')
  if (action === 'session') {
    return syncIdTokenCookie(req, response)
  }

  if (isCallback) {
    console.log('[NextAuth] Syncing idToken cookie after callback')
    return syncIdTokenCookie(req, response)
  }

  return response
}

export const GET = withIdTokenCookie
export const POST = withIdTokenCookie
