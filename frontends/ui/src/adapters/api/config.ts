// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * API Configuration
 *
 * Server-side: Reads BACKEND_URL env var at runtime (no rebuild needed)
 * Client-side: Uses same-origin URLs (proxied through UI server)
 */

interface ApiConfig {
  baseUrl: string
  chatStreamUrl: string
  generateStreamUrl: string
  chatApiRoute: string
  generateApiRoute: string
  websocketUrl: string
  healthUrl: string
  timeout: number
  documentsBaseUrl: string
  collectionsUrl: string
}

const isServer = typeof window === 'undefined'

const getBaseUrl = (): string => {
  const url = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  return url.replace(/\/$/, '')
}

/**
 * Get WebSocket URL.
 * - Server-side: Returns backend WebSocket URL directly
 * - Client-side: Returns same-origin URL (proxied through UI server)
 */
export const getWebSocketUrl = async (): Promise<string> => {
  if (isServer) {
    const baseUrl = getBaseUrl()
    return `${baseUrl.replace(/^http/, 'ws')}/websocket`
  }

  // Browser: connect to same origin, UI server proxies to backend
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/websocket`
}

export const apiConfig: ApiConfig = {
  baseUrl: getBaseUrl(),
  chatStreamUrl: `${getBaseUrl()}/chat/stream`,
  generateStreamUrl: `${getBaseUrl()}/generate/stream`,
  chatApiRoute: '/api/chat',
  generateApiRoute: '/api/generate',
  websocketUrl: `${getBaseUrl().replace(/^http/, 'ws')}/websocket`,
  healthUrl: `${getBaseUrl()}/health`,
  timeout: 30000,
  documentsBaseUrl: `${getBaseUrl()}/v1`,
  collectionsUrl: `${getBaseUrl()}/v1/collections`,
}

export const checkBackendHealth = async (): Promise<boolean> => {
  try {
    // Client-side: use same-origin proxy route (backend may not be publicly exposed)
    // Server-side: hit backend directly
    const url = isServer ? apiConfig.healthUrl : '/api/health'
    const response = await fetch(url, {
      method: 'GET',
      signal: AbortSignal.timeout(5000),
    })
    return response.ok
  } catch {
    return false
  }
}
