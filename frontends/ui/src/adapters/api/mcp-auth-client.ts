// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MCP Auth API Client
 *
 * Per-user MCP OAuth control plane: read a protected source's connection
 * status, start the connect flow (returns a provider login URL), and a helper
 * to open that URL in a popup and resolve once the popup closes or the callback
 * page posts back.
 */

import { apiConfig } from './config'
import type { PerUserAuthStatus } from './data-sources-client'

const getBaseUrl = (): string => {
  const isBrowser = typeof window !== 'undefined'
  return isBrowser ? '' : apiConfig.baseUrl
}

const apiUrl = (path: string): string => {
  const baseUrl = getBaseUrl()
  return baseUrl ? `${baseUrl}${path}` : `/api${path}`
}

// ============================================================================
// Types
// ============================================================================

export interface SourceAuthStatusResponse {
  source_id: string
  status: PerUserAuthStatus
  expires_at?: string | null
  connect_url?: string | null
  last_error?: string | null
}

export interface SourceConnectResponse {
  source_id: string
  status: 'auth_required' | 'connected'
  auth_url?: string | null
  expires_at?: string | null
}

export interface McpAuthClientOptions {
  authToken?: string
}

// ============================================================================
// Client Factory
// ============================================================================

export const createMcpAuthClient = (options: McpAuthClientOptions = {}) => {
  const { authToken } = options

  const getHeaders = (): Record<string, string> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`
    }
    return headers
  }

  return {
    /** Read the current per-user auth status for a protected source. */
    async getStatus(sourceId: string, signal?: AbortSignal): Promise<SourceAuthStatusResponse> {
      const response = await fetch(apiUrl(`/v1/auth/mcp/${encodeURIComponent(sourceId)}/status`), {
        method: 'GET',
        headers: getHeaders(),
        signal,
      })
      if (!response.ok) {
        throw new Error(`Failed to fetch auth status: ${response.statusText}`)
      }
      return response.json()
    },

    /** Start (or resume) the OAuth flow; returns a provider login URL to open. */
    async connect(sourceId: string): Promise<SourceConnectResponse> {
      const response = await fetch(apiUrl(`/v1/auth/mcp/${encodeURIComponent(sourceId)}/connect`), {
        method: 'POST',
        headers: getHeaders(),
      })
      if (!response.ok) {
        throw new Error(`Failed to start connection: ${response.statusText}`)
      }
      return response.json()
    },
  }
}

export type McpAuthClient = ReturnType<typeof createMcpAuthClient>

// ============================================================================
// Popup helper
// ============================================================================

export interface AuthPopupResult {
  /** True if the callback page reported success via postMessage. Undefined if we
   *  only observed the window closing (caller should re-check status). */
  ok?: boolean
  /** The source id reported by the callback page, if any. */
  sourceId?: string
}

/**
 * Open the provider login URL in a popup and resolve when it closes or the
 * callback page posts back. The caller should re-fetch the source status after
 * this resolves to confirm the connection (popup-close is not proof of success).
 */
export function openAuthPopupAndWait(authUrl: string, sourceId: string): Promise<AuthPopupResult> {
  return new Promise((resolve) => {
    const popup = window.open(authUrl, `mcp-auth-${sourceId}`, 'popup,width=520,height=680')

    // Popup blocked — fall back to a same-tab redirect is too disruptive, so
    // resolve immediately and let the caller surface the URL / re-check status.
    if (!popup) {
      resolve({})
      return
    }

    let settled = false
    const finish = (result: AuthPopupResult) => {
      if (settled) return
      settled = true
      window.removeEventListener('message', onMessage)
      clearInterval(poll)
      resolve(result)
    }

    const onMessage = (event: MessageEvent) => {
      const data = event.data
      if (data && data.type === 'mcp-auth' && data.source_id === sourceId) {
        try {
          popup.close()
        } catch {
          /* ignore */
        }
        finish({ ok: !!data.ok, sourceId })
      }
    }
    window.addEventListener('message', onMessage)

    const poll = setInterval(() => {
      if (popup.closed) {
        finish({})
      }
    }, 700)
  })
}
