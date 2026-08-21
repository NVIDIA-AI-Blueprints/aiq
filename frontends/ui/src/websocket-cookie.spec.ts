// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import cookieFilter from '../websocket-cookie.js'

const { forwardWebSocketAuthCookie, getWebSocketAuthCookie } = cookieFilter

describe('getWebSocketAuthCookie', () => {
  test('forwards only the backend authentication cookie', () => {
    const session = 's'.repeat(9000)
    const header = `next-auth.session-token=${session}; idToken=jwt-value; route=frontend`

    expect(getWebSocketAuthCookie(header)).toBe('idToken=jwt-value')
  })

  test('uses the first non-empty ID token when duplicate paths exist', () => {
    const header = 'idToken=preferred; idToken=stale; route=frontend'

    expect(getWebSocketAuthCookie(header)).toBe('idToken=preferred')
  })

  test.each([undefined, '', 'route=frontend', 'idToken='])('omits cookies when no usable ID token exists', (header) => {
    expect(getWebSocketAuthCookie(header)).toBeUndefined()
  })
})

describe('forwardWebSocketAuthCookie', () => {
  const createProxyRequest = (cookie?: string) => {
    const headers = new Map<string, string>()
    if (cookie) headers.set('cookie', cookie)

    return {
      getHeader: (name: string) => headers.get(name.toLowerCase()),
      removeHeader: (name: string) => headers.delete(name.toLowerCase()),
      setHeader: (name: string, value: string) => headers.set(name.toLowerCase(), value),
    }
  }

  test('replaces the incoming cookie header with only the ID token', () => {
    const incomingCookie = `next-auth.session-token=${'s'.repeat(9000)}; idToken=jwt-value; route=frontend`
    const proxyReq = createProxyRequest(incomingCookie)

    forwardWebSocketAuthCookie(proxyReq, { headers: { cookie: incomingCookie } })

    expect(proxyReq.getHeader('Cookie')).toBe('idToken=jwt-value')
  })

  test('removes the incoming cookie header when no usable ID token exists', () => {
    const incomingCookie = 'next-auth.session-token=session-value; route=frontend'
    const proxyReq = createProxyRequest(incomingCookie)

    forwardWebSocketAuthCookie(proxyReq, { headers: { cookie: incomingCookie } })

    expect(proxyReq.getHeader('Cookie')).toBeUndefined()
  })
})
