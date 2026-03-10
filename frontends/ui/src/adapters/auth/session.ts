// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Session Hook Adapter
 *
 * Provides typed session hooks for use in features.
 * Wraps NextAuth's useSession with additional functionality.
 *
 * When REQUIRE_AUTH=false (server-side env var), returns a mock authenticated user
 * without requiring OAuth authentication.
 */

'use client'

import { useCallback, useEffect, useRef } from 'react'
import { useSession as useNextAuthSession, signIn, signOut } from 'next-auth/react'
import { useAppConfig } from '@/shared/context'
import { type AuthContext } from './types'

/**
 * Default user returned when authentication is disabled.
 */
const DEFAULT_USER = {
  id: 'default-user',
  name: 'Default User',
  email: null,
  image: null,
}

/**
 * Hook for accessing the current authentication state and actions
 *
 * Automatically handles token refresh errors by triggering re-authentication
 * when the refresh token is invalid or expired.
 *
 * @example
 * ```tsx
 * const { user, isAuthenticated, isLoading, idToken, signIn, signOut, authRequired } = useAuth()
 *
 * if (isLoading) return <Spinner />
 * if (!isAuthenticated) return <Button onClick={signIn}>Sign In</Button>
 *
 * // Use idToken for backend API calls (not available when !authRequired)
 * if (idToken) {
 *   await fetch('/api/data', {
 *     headers: { 'Authorization': `Bearer ${idToken}` }
 *   })
 * }
 *
 * return <Text>Welcome, {user?.name}</Text>
 * ```
 */
export const useAuth = (): AuthContext => {
  const { authRequired, authProviderId, sessionRefreshIntervalSeconds } = useAppConfig()
  const authRequiredRef = useRef(authRequired)
  const { data: session, status, update } = useNextAuthSession()
  const hasTriggeredReauth = useRef(false)

  if (authRequiredRef.current !== authRequired) {
    throw new Error('Auth configuration changed at runtime')
  }

  const handleSignIn = useCallback(async (): Promise<void> => {
    await signIn(authProviderId, { callbackUrl: '/' })
  }, [authProviderId])

  const handleSignOut = useCallback(async (): Promise<void> => {
    await signOut({ callbackUrl: '/auth/signin' })
  }, [])

  useEffect(() => {
    if (!authRequired) return

    const error = session?.error
    if (error && !hasTriggeredReauth.current) {
      if (error === 'RefreshAccessTokenError') {
        hasTriggeredReauth.current = true
        console.warn('[Auth] Token refresh failed, redirecting to sign in')
        handleSignOut()
      }
    }
  }, [session?.error, authRequired, handleSignOut])

  useEffect(() => {
    if (!authRequired) return
    if (status !== 'authenticated') return

    const interval = setInterval(() => {
      update()
    }, sessionRefreshIntervalSeconds * 1000)

    return () => clearInterval(interval)
  }, [status, update, authRequired, sessionRefreshIntervalSeconds])

  if (!authRequired) {
    return {
      isAuthenticated: true,
      isLoading: false,
      authRequired: false,
      user: DEFAULT_USER,
      accessToken: undefined,
      idToken: undefined,
      error: undefined,
      signIn: async () => {},
      signOut: async () => {},
    }
  }

  const isLoading = status === 'loading'
  const hasValidToken = !session?.error && !!session?.idToken
  const isAuthenticated = status === 'authenticated' && !!session?.user && hasValidToken

  return {
    isAuthenticated,
    isLoading,
    authRequired: true,
    user: session?.user
      ? {
          id: session.userId || session.user.email || undefined,
          email: session.user.email,
          name: session.user.name,
          image: session.user.image,
        }
      : null,
    accessToken: session?.accessToken,
    idToken: session?.idToken,
    error: session?.error,
    signIn: handleSignIn,
    signOut: handleSignOut,
  }
}
