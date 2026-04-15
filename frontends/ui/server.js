// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Gateway Server with WebSocket Proxy
 *
 * Architecture (following Nemo-Agent-Toolkit-UI pattern):
 * - Runs on port 3000 as the main entry point
 * - Proxies to Next.js server (dev on 3001, or production on same process)
 * - Proxies /websocket to backend WebSocket endpoint
 *
 * Development:
 *   npm run dev - Runs gateway + Next.js dev server concurrently
 *
 * Production:
 *   npm start - Runs Next.js in production mode with integrated proxy
 *
 * Environment:
 *   BACKEND_URL - Backend service URL (e.g., http://backend:8000)
 *   PORT - Gateway port (default: 3000)
 *   NEXT_INTERNAL_URL - Next.js server URL (default: http://localhost:3001)
 */

const http = require('http')
const httpProxy = require('http-proxy')
const { parse } = require('url')
const { decode: decodeJwt } = require('next-auth/jwt')

const dev = process.env.NODE_ENV !== 'production'
const hostname = process.env.HOSTNAME || '0.0.0.0'
const port = parseInt(process.env.PORT || '3000', 10)

const getBackendUrl = () => {
  const url = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  return url.replace(/\/$/, '')
}

const getBackendWsUrl = () => {
  const baseUrl = getBackendUrl()
  return baseUrl.replace(/^http/, 'ws')
}

const BACKEND_HTTP_URL = getBackendUrl()
const BACKEND_WS_URL = getBackendWsUrl()
const NEXT_INTERNAL_URL = process.env.NEXT_INTERNAL_URL || 'http://localhost:3001'
const NEXTAUTH_SECRET = process.env.NEXTAUTH_SECRET

/**
 * Parse cookies from a raw Cookie header string.
 */
const parseCookies = (cookieHeader) => {
  const cookies = {}
  if (!cookieHeader) return cookies
  for (const part of cookieHeader.split(';')) {
    const idx = part.indexOf('=')
    if (idx > 0) {
      cookies[part.slice(0, idx).trim()] = part.slice(idx + 1).trim()
    }
  }
  return cookies
}

/**
 * Extract idToken from the NextAuth session JWT cookie.
 *
 * proxy.ts (Next.js middleware) sets the idToken cookie on HTTP responses,
 * but WebSocket upgrades bypass Next.js entirely — the gateway handles them
 * directly. If the browser hasn't received a recent HTTP response that set
 * the cookie (first load, expired token, stale cache), the WebSocket
 * connects without auth and downstream services that need the caller's
 * identity (e.g. ECI search) fail.
 *
 * This function decodes the NextAuth session JWT (which the browser always
 * sends) and extracts the idToken so the gateway can inject it into the
 * proxied WebSocket request.
 */
const extractIdTokenFromSession = async (cookieHeader) => {
  if (!NEXTAUTH_SECRET) return null
  const cookies = parseCookies(cookieHeader)

  // NextAuth 4 uses prefixed names when NEXTAUTH_URL is HTTPS
  const sessionToken =
    cookies['__Secure-next-auth.session-token'] ||
    cookies['next-auth.session-token']
  if (!sessionToken) return null

  try {
    const decoded = await decodeJwt({
      token: sessionToken,
      secret: NEXTAUTH_SECRET,
    })
    if (!decoded || decoded.error) return null
    const expiresAt = decoded.expiresAt
    if (!expiresAt || Date.now() >= expiresAt * 1000) return null
    return decoded.idToken || null
  } catch (err) {
    console.error('[WS Auth] Failed to decode NextAuth session:', err.message)
    return null
  }
}

// In production, we run Next.js in the same process
let nextApp = null
let nextHandle = null

if (!dev) {
  const next = require('next')
  nextApp = next({ dev: false, hostname, port: 3001 })
  nextHandle = nextApp.getRequestHandler()
}

// Create proxy for Next.js (used in dev mode)
const nextProxy = httpProxy.createProxyServer({
  target: NEXT_INTERNAL_URL,
  changeOrigin: true,
  ws: true,
  xfwd: true,
  preserveHeaderKeyCase: true,
})

// Create proxy for backend
const backendProxy = httpProxy.createProxyServer({
  changeOrigin: true,
  ws: true,
  xfwd: true,
  preserveHeaderKeyCase: true,
})

// Error handling for Next.js proxy
nextProxy.on('error', (err, req, res) => {
  console.error('[Next.js Proxy Error]:', err.message)
  if (res && res.writeHead && !res.headersSent) {
    res.writeHead(502, { 'Content-Type': 'application/json' })
  }
  if (res && !res.writableEnded) {
    res.end(JSON.stringify({ error: 'Next.js server unavailable' }))
  }
})

// Error handling for backend proxy
backendProxy.on('error', (err, req, res) => {
  console.error('[Backend Proxy Error]:', err.message)
  if (res && res.writeHead && !res.headersSent) {
    res.writeHead(502, { 'Content-Type': 'application/json' })
  }
  if (res && !res.writableEnded) {
    res.end(JSON.stringify({ error: 'Backend unavailable' }))
  }
})

// WebSocket keep-alive for backend
backendProxy.on('open', (proxySocket) => {
  try {
    proxySocket.setKeepAlive?.(true, 15000)
    proxySocket.on('error', (e) =>
      console.error('[WebSocket] upstream socket error:', e.message)
    )
  } catch {}
})

// Forward cookies for backend WebSocket
backendProxy.on('proxyReqWs', (proxyReq, req) => {
  if (req.headers.cookie) {
    proxyReq.setHeader('Cookie', req.headers.cookie)
  }
})

const startServer = async () => {
  // In production, prepare Next.js
  if (!dev && nextApp) {
    await nextApp.prepare()
  }

  const server = http.createServer(async (req, res) => {
    req.socket.setKeepAlive?.(true, 15000)
    req.socket.setTimeout?.(0)

    let parsedUrl
    try {
      parsedUrl = parse(req.url, true)
    } catch {
      res.writeHead(400, { 'Content-Type': 'text/plain' })
      res.end('Bad Request')
      return
    }

    if (dev) {
      // Development: proxy everything to Next.js dev server
      nextProxy.web(req, res, { target: NEXT_INTERNAL_URL })
    } else {
      // Production: handle with Next.js directly
      try {
        await nextHandle(req, res, parsedUrl)
      } catch (err) {
        console.error('Error handling request:', err)
        res.statusCode = 500
        res.end('Internal Server Error')
      }
    }
  })

  // WebSocket upgrade handler
  server.on('upgrade', async (req, socket, head) => {
    socket.setKeepAlive?.(true, 15000)
    socket.setTimeout?.(0)

    let parsedUrl
    try {
      parsedUrl = parse(req.url, true)
    } catch {
      socket.destroy()
      return
    }
    const pathname = parsedUrl.pathname || '/'

    // Proxy /websocket to backend
    if (pathname === '/websocket' || pathname.startsWith('/websocket')) {
      req.url = '/websocket' + (parsedUrl.search || '')

      // Ensure the backend receives a fresh idToken for auth.
      // proxy.ts (Next.js middleware) sets the idToken cookie on HTTP
      // responses, but WebSocket upgrades bypass Next.js. The browser may
      // send a stale or missing idToken cookie while the NextAuth session
      // JWT (refreshed every ~30 min by the JWT callback) has the latest
      // token. Always prefer the session JWT so the backend gets the
      // freshest credential.
      const idToken = await extractIdTokenFromSession(req.headers.cookie)
      if (idToken) {
        // Strip any existing idToken cookie and inject the fresh one
        const cookieParts = (req.headers.cookie || '')
          .split(';')
          .filter((c) => !c.trim().startsWith('idToken='))
        cookieParts.push(`idToken=${idToken}`)
        req.headers.cookie = cookieParts.join('; ')
      }

      backendProxy.ws(
        req,
        socket,
        head,
        { target: BACKEND_WS_URL, changeOrigin: true },
        (err) => {
          if (err) {
            console.error('[WS Proxy] Error:', err.message)
            try {
              socket.write('HTTP/1.1 502 Bad Gateway\r\n\r\n')
            } catch {}
            socket.destroy()
          }
        }
      )
      return
    }

    // All other WebSocket connections (HMR, etc.)
    if (dev) {
      // Development: proxy to Next.js dev server
      nextProxy.ws(req, socket, head, { target: NEXT_INTERNAL_URL }, (err) => {
        if (err) {
          console.error('[Next.js WS] Proxy error:', err.message)
          socket.destroy()
        }
      })
    } else {
      // Production: let Next.js handle it
      const upgradeHandler = nextApp.getUpgradeHandler()
      upgradeHandler(req, socket, head)
    }
  })

  // Server configuration for long-running connections
  server.keepAliveTimeout = 0
  server.headersTimeout = 65000
  server.requestTimeout = 0

  server.listen(port, hostname, () => {
    console.log(`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Frontend: http://localhost:${port}
  Backend:  ${BACKEND_HTTP_URL}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`)
  })

  // Graceful shutdown
  const cleanExit = (signal) => {
    console.log(`\nShutting down (${signal})...`)
    server.close(() => process.exit(0))
    setTimeout(() => process.exit(0), 2000)
  }

  process.once('SIGTERM', () => cleanExit('SIGTERM'))
  process.once('SIGINT', () => cleanExit('SIGINT'))
}

startServer().catch((err) => {
  console.error('Failed to start server:', err)
  process.exit(1)
})
