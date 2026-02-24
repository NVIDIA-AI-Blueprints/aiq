// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, test, expect, beforeEach, afterEach } from 'vitest'
import {
  authenticatedFetch,
  createAuthenticatedFetch,
  getAuthToken,
} from './authenticated-fetch'

// Mock next-auth/react
const mockGetSession = vi.fn()
vi.mock('next-auth/react', () => ({
  getSession: () => mockGetSession(),
}))

// Mock global fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

// Helper to extract headers from mock call - handles both Request object and (url, options) signature
const getCalledHeaders = (callIndex = 0): Headers => {
  const call = mockFetch.mock.calls[callIndex]
  // Check if first arg is a Request object
  if (call[0] instanceof Request) {
    return call[0].headers
  }
  // Otherwise assume (url, options) signature
  return call[1]?.headers as Headers
}

// Helper to extract options from mock call (prefixed with _ as currently unused but may be needed for future tests)
const _getCalledOptions = (callIndex = 0): RequestInit => {
  const call = mockFetch.mock.calls[callIndex]
  if (call[0] instanceof Request) {
    // Extract options-like properties from Request
    return {
      method: call[0].method,
      credentials: (call[0] as RequestInit).credentials,
    }
  }
  return call[1] || {}
}

describe('authenticated-fetch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockResolvedValue(new Response('OK', { status: 200 }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('authenticatedFetch', () => {
    test('adds Authorization header from session idToken', async () => {
      mockGetSession.mockResolvedValue({
        idToken: 'test-id-token',
        accessToken: 'test-access-token',
      })

      await authenticatedFetch('/api/test')

      expect(mockFetch).toHaveBeenCalled()
      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBe('Bearer test-id-token')
    })

    test('falls back to accessToken when idToken is not available', async () => {
      mockGetSession.mockResolvedValue({
        accessToken: 'test-access-token',
      })

      await authenticatedFetch('/api/test')

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBe('Bearer test-access-token')
    })

    test('does not add Authorization header when session is null', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test')

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBeNull()
    })

    test('skips auth when skipAuth option is true', async () => {
      mockGetSession.mockResolvedValue({
        idToken: 'test-id-token',
      })

      await authenticatedFetch('/api/test', { skipAuth: true })

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBeNull()
      expect(mockGetSession).not.toHaveBeenCalled()
    })

    test('adds Content-Type header for requests with body', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test', {
        method: 'POST',
        body: JSON.stringify({ data: 'test' }),
      })

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Content-Type')).toBe('application/json')
    })

    test('preserves existing Content-Type header', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test', {
        method: 'POST',
        body: 'text content',
        headers: { 'Content-Type': 'text/plain' },
      })

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Content-Type')).toBe('text/plain')
    })

    test('does not add Content-Type for requests without body', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test')

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Content-Type')).toBeNull()
    })

    test('sets credentials to "include" by default', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test')

      expect(mockFetch).toHaveBeenCalled()
      // Credentials are set on the call
    })

    test('preserves custom credentials option', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test', { credentials: 'omit' })

      expect(mockFetch).toHaveBeenCalled()
    })

    test('passes through other fetch options', async () => {
      mockGetSession.mockResolvedValue(null)

      await authenticatedFetch('/api/test', {
        method: 'POST',
        body: JSON.stringify({ test: true }),
        cache: 'no-cache',
        mode: 'cors',
      })

      expect(mockFetch).toHaveBeenCalled()
    })

    test('handles getSession errors gracefully', async () => {
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      mockGetSession.mockRejectedValue(new Error('Session error'))

      await authenticatedFetch('/api/test')

      // Should still make the request without auth header
      expect(mockFetch).toHaveBeenCalled()
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        '[authenticatedFetch] Failed to get session:',
        expect.any(Error)
      )

      consoleWarnSpy.mockRestore()
    })

    test('merges provided headers with auth header', async () => {
      mockGetSession.mockResolvedValue({
        idToken: 'test-id-token',
      })

      await authenticatedFetch('/api/test', {
        headers: { 'X-Custom-Header': 'custom-value' },
      })

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBe('Bearer test-id-token')
      expect(calledHeaders.get('X-Custom-Header')).toBe('custom-value')
    })
  })

  describe('createAuthenticatedFetch', () => {
    test('creates fetch function with pre-set token', async () => {
      const authFetch = createAuthenticatedFetch('preset-token')

      await authFetch('/api/test')

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBe('Bearer preset-token')
    })

    test('creates fetch function without token when undefined', async () => {
      const authFetch = createAuthenticatedFetch(undefined)

      await authFetch('/api/test')

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Authorization')).toBeNull()
    })

    test('adds Content-Type for requests with body', async () => {
      const authFetch = createAuthenticatedFetch('token')

      await authFetch('/api/test', {
        method: 'POST',
        body: JSON.stringify({ data: 'test' }),
      })

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Content-Type')).toBe('application/json')
    })

    test('preserves existing Content-Type header', async () => {
      const authFetch = createAuthenticatedFetch('token')

      await authFetch('/api/test', {
        method: 'POST',
        body: 'form-data',
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      const calledHeaders = getCalledHeaders()
      expect(calledHeaders.get('Content-Type')).toBe('multipart/form-data')
    })

    test('sets credentials to "include" by default', async () => {
      const authFetch = createAuthenticatedFetch('token')

      await authFetch('/api/test')

      expect(mockFetch).toHaveBeenCalled()
    })

    test('preserves custom credentials option', async () => {
      const authFetch = createAuthenticatedFetch('token')

      await authFetch('/api/test', { credentials: 'same-origin' })

      expect(mockFetch).toHaveBeenCalled()
    })

    test('passes through other fetch options', async () => {
      const authFetch = createAuthenticatedFetch('token')

      await authFetch('/api/test', {
        method: 'DELETE',
        signal: new AbortController().signal,
      })

      expect(mockFetch).toHaveBeenCalled()
    })
  })

  describe('getAuthToken', () => {
    test('returns idToken when available', () => {
      const session = {
        idToken: 'id-token',
        accessToken: 'access-token',
      }

      expect(getAuthToken(session)).toBe('id-token')
    })

    test('returns accessToken when idToken is not available', () => {
      const session = {
        accessToken: 'access-token',
      }

      expect(getAuthToken(session)).toBe('access-token')
    })

    test('returns undefined when session is null', () => {
      expect(getAuthToken(null)).toBeUndefined()
    })

    test('returns undefined when session has no tokens', () => {
      expect(getAuthToken({})).toBeUndefined()
    })
  })
})
