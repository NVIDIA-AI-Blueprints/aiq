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

export interface AuthPopupOptions {
  /**
   * Optional backend status probe. When provided, the popup also resolves as
   * soon as the source reports a terminal status. This is the reliable signal:
   * the provider's pages typically send `Cross-Origin-Opener-Policy`, which
   * severs `window.opener` so the callback's `postMessage` and the parent's
   * `popup.closed` check both go silent — leaving the card stuck on
   * "Connecting…". The callback persists the token before it messages the
   * opener, so a status probe sees the result regardless.
   */
  pollStatus?: () => Promise<PerUserAuthStatus | undefined>
  /** How often to probe backend status, in ms. Default 1500. */
  pollIntervalMs?: number
  /** Stop waiting after this long, in ms, so a never-finished login can't poll
   *  forever. Default 180000 (3 min). */
  timeoutMs?: number
}

/**
 * Open the provider login URL in a popup and resolve when it closes, the
 * callback page posts back, or (when `pollStatus` is supplied) the backend
 * reports a terminal status. The caller should still re-fetch the source status
 * after this resolves to confirm the connection.
 */
export function openAuthPopupAndWait(
  authUrl: string,
  sourceId: string,
  options: AuthPopupOptions = {}
): Promise<AuthPopupResult> {
  const { pollStatus, pollIntervalMs = 1500, timeoutMs = 180_000 } = options
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
      if (statusPoll !== undefined) clearInterval(statusPoll)
      clearTimeout(timeout)
      resolve(result)
    }

    const onMessage = (event: MessageEvent) => {
      // Only trust messages from the popup we opened: the callback page posts via
      // window.opener.postMessage, so a genuine completion has event.source === popup.
      // Reject anything else (a synthetic or cross-window message) so an unrelated
      // page can't spoof an auth-complete. If COOP severs the opener relationship
      // event.source won't match — the status poll below is the fallback for that.
      if (event.source !== popup) return
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

    // Authoritative resolve path: poll the backend until the source reaches a
    // terminal status. Survives the COOP opener-severing described above.
    //
    // `expired`/`error` are the PRE-EXISTING states that make the card show
    // "Reconnect", so they're also what the first poll sees before the user has
    // authenticated. Treating them as terminal would close the popup ~1.5s after
    // it opens (UI: "Session expired") before login can complete. So we snapshot
    // the baseline on the first probe and only resolve on a real transition:
    // `connected` (success), or a NEW `error` that differs from the baseline.
    let baselineStatus: PerUserAuthStatus | undefined
    const statusPoll: ReturnType<typeof setInterval> | undefined = pollStatus
      ? setInterval(() => {
          void (async () => {
            let status: PerUserAuthStatus | undefined
            try {
              status = await pollStatus()
            } catch {
              return // transient probe failure — keep polling
            }
            if (baselineStatus === undefined) baselineStatus = status
            const succeeded = status === 'connected'
            const newlyErrored = status === 'error' && baselineStatus !== 'error'
            if (succeeded || newlyErrored) {
              try {
                popup.close()
              } catch {
                /* ignore */
              }
              finish({ ok: succeeded, sourceId })
            }
          })()
        }, pollIntervalMs)
      : undefined

    const timeout = setTimeout(() => finish({}), timeoutMs)
  })
}
