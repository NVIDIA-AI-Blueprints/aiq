// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for useAuth hook
 *
 * Verifies authentication state management including:
 * - Token validation
 * - Error handling for expired tokens
 * - authRequired flag for bypass mode
 */

import { type ReactNode } from 'react'
import { renderHook } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AppConfigProvider, type AppConfig } from '@/shared/context'

// Mock functions need to be defined before vi.mock calls
const mockUseSessionFn = vi.fn()
const mockSignInFn = vi.fn()
const mockSignOutFn = vi.fn()

// Mock next-auth/react
vi.mock('next-auth/react', () => ({
  useSession: () => mockUseSessionFn(),
  signIn: (...args: unknown[]) => mockSignInFn(...args),
  signOut: (...args: unknown[]) => mockSignOutFn(...args),
}))

import { useAuth } from './session'

/**
 * Default file upload config for tests
 */
const defaultFileUploadConfig = {
  acceptedTypes: '.pdf,.docx,.txt,.md',
  acceptedMimeTypes: ['application/pdf', 'text/plain', 'text/markdown'],
  maxTotalSizeMB: 100,
  maxFileSize: 100 * 1024 * 1024,
  maxTotalSize: 100 * 1024 * 1024,
  maxFileCount: 10,
  fileExpirationCheckIntervalHours: 0,
}

/**
 * Test wrapper that provides required context
 */
const createWrapper = (
  config: AppConfig = { authRequired: true, authProviderId: 'oauth', sessionRefreshIntervalSeconds: 240, fileUpload: defaultFileUploadConfig }
) => {
  const Wrapper = ({ children }: { children: ReactNode }): ReactNode => (
    <AppConfigProvider config={config}>{children}</AppConfigProvider>
  )
  Wrapper.displayName = 'TestWrapper'
  return Wrapper
}

describe('useAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('authentication state', () => {
    test('returns loading state when session is loading', () => {
      mockUseSessionFn.mockReturnValue({ data: null, status: 'loading' })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      expect(result.current.isLoading).toBe(true)
      expect(result.current.isAuthenticated).toBe(false)
      expect(result.current.authRequired).toBe(true)
    })

    test('returns authenticated when user exists with valid token', () => {
      mockUseSessionFn.mockReturnValue({
        data: {
          user: { email: 'test@example.com', name: 'Test User' },
          idToken: 'valid-jwt-token',
          accessToken: 'access-token',
          error: undefined,
        },
        status: 'authenticated',
      })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      expect(result.current.isAuthenticated).toBe(true)
      expect(result.current.authRequired).toBe(true)
      expect(result.current.user?.email).toBe('test@example.com')
      expect(result.current.idToken).toBe('valid-jwt-token')
      expect(result.current.error).toBeUndefined()
    })

    test('returns unauthenticated when user exists but idToken is missing', () => {
      mockUseSessionFn.mockReturnValue({
        data: {
          user: { email: 'test@example.com', name: 'Test User' },
          idToken: undefined, // Token missing
          accessToken: 'access-token',
          error: undefined,
        },
        status: 'authenticated',
      })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      // Should be unauthenticated because idToken is missing
      // Note: user info is still returned for display purposes, but isAuthenticated is false
      expect(result.current.isAuthenticated).toBe(false)
      expect(result.current.authRequired).toBe(true)
      expect(result.current.idToken).toBeUndefined()
    })

    test('returns unauthenticated when RefreshAccessTokenError occurs', () => {
      mockUseSessionFn.mockReturnValue({
        data: {
          user: { email: 'test@example.com', name: 'Test User' },
          idToken: 'stale-token',
          accessToken: 'access-token',
          error: 'RefreshAccessTokenError', // Token refresh failed
        },
        status: 'authenticated',
      })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      // Should be unauthenticated because token refresh failed
      expect(result.current.isAuthenticated).toBe(false)
      expect(result.current.authRequired).toBe(true)
      expect(result.current.error).toBe('RefreshAccessTokenError')
    })

    test('returns unauthenticated when session is not authenticated', () => {
      mockUseSessionFn.mockReturnValue({
        data: null,
        status: 'unauthenticated',
      })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      expect(result.current.isAuthenticated).toBe(false)
      expect(result.current.authRequired).toBe(true)
      expect(result.current.user).toBeNull()
      expect(result.current.idToken).toBeUndefined()
    })
  })

  describe('sign in/out actions', () => {
    test('signIn calls next-auth signIn with oauth provider', async () => {
      mockUseSessionFn.mockReturnValue({
        data: null,
        status: 'unauthenticated',
      })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      await result.current.signIn()

      expect(mockSignInFn).toHaveBeenCalledWith('oauth', { callbackUrl: '/' })
    })

    test('signOut calls next-auth signOut with redirect', async () => {
      mockUseSessionFn.mockReturnValue({
        data: {
          user: { email: 'test@example.com' },
          idToken: 'valid-token',
        },
        status: 'authenticated',
      })

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() })

      await result.current.signOut()

      expect(mockSignOutFn).toHaveBeenCalledWith({ callbackUrl: '/auth/signin' })
    })
  })

  describe('auth disabled mode', () => {
    test('returns mock authenticated user when auth is disabled', () => {
      // Session return value should be irrelevant when auth is disabled
      mockUseSessionFn.mockReturnValue({ data: null, status: 'unauthenticated' })

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper({ authRequired: false, authProviderId: 'disabled-auth', sessionRefreshIntervalSeconds: 240, fileUpload: defaultFileUploadConfig }),
      })

      expect(result.current.isAuthenticated).toBe(true)
      expect(result.current.authRequired).toBe(false)
      expect(result.current.isLoading).toBe(false)
      expect(result.current.user?.name).toBe('Default User')
      expect(result.current.idToken).toBeUndefined()
    })

    test('signIn and signOut are no-ops when auth is disabled', async () => {
      mockUseSessionFn.mockReturnValue({ data: null, status: 'unauthenticated' })

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper({ authRequired: false, authProviderId: 'disabled-auth', sessionRefreshIntervalSeconds: 240, fileUpload: defaultFileUploadConfig }),
      })

      await result.current.signIn()
      await result.current.signOut()

      // Should not call the real sign in/out functions
      expect(mockSignInFn).not.toHaveBeenCalled()
      expect(mockSignOutFn).not.toHaveBeenCalled()
    })
  })
})
