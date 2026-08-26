// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Return the single authentication cookie required by the backend WebSocket.
 *
 * Forwarding the browser's complete Cookie header can exceed the WebSocket
 * server's HTTP header limit because it includes the NextAuth session and
 * ingress-affinity cookies in addition to the ID token. Cookie ordering puts
 * the most specific path first, so the first non-empty idToken is authoritative
 * when stale cookies with the same name exist at multiple paths.
 *
 * @param {string | undefined} cookieHeader
 * @returns {string | undefined}
 */
const getWebSocketAuthCookie = (cookieHeader) => {
  if (!cookieHeader) return undefined

  for (const rawCookie of cookieHeader.split(';')) {
    const cookie = rawCookie.trim()
    const separator = cookie.indexOf('=')
    if (separator <= 0) continue

    const name = cookie.slice(0, separator)
    const value = cookie.slice(separator + 1)
    if (name === 'idToken' && value) return `idToken=${value}`
  }

  return undefined
}

/**
 * Restrict the outgoing WebSocket request to the backend authentication
 * cookie. http-proxy initially copies all incoming headers, so Cookie must be
 * removed even when no usable ID token is present.
 *
 * @param {{ removeHeader: (name: string) => void, setHeader: (name: string, value: string) => void }} proxyReq
 * @param {{ headers: { cookie?: string } }} req
 */
const forwardWebSocketAuthCookie = (proxyReq, req) => {
  const authCookie = getWebSocketAuthCookie(req.headers.cookie)
  proxyReq.removeHeader('Cookie')
  if (authCookie) proxyReq.setHeader('Cookie', authCookie)
}

module.exports = { forwardWebSocketAuthCookie, getWebSocketAuthCookie }
