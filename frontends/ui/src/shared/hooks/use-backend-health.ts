// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Backend Health Check Utility
 *
 * Provides a cached, on-demand health check for the backend.
 * Used to gate connection error display -- before showing a connection
 * error to the user, verify the backend is actually down via /health.
 *
 * Not a polling service: only checks when explicitly called.
 * Results are cached for a short window to avoid hammering /health
 * during rapid error events (e.g. multiple WS close/error cycles).
 */

import { checkBackendHealth } from '@/adapters/api/config'

/** Cache duration in milliseconds */
const CACHE_TTL_MS = 5_000

let cachedResult: boolean | null = null
let cachedAt = 0

/**
 * Check backend health with short-lived cache.
 *
 * - Returns cached result if checked within the last 5 seconds.
 * - Otherwise makes a fresh GET /health request.
 * - Returns `true` if the backend is reachable, `false` if not.
 */
export const checkBackendHealthCached = async (): Promise<boolean> => {
  const now = Date.now()

  if (cachedResult !== null && now - cachedAt < CACHE_TTL_MS) {
    return cachedResult
  }

  const isHealthy = await checkBackendHealth()
  cachedResult = isHealthy
  cachedAt = now
  return isHealthy
}

/**
 * Invalidate the health cache.
 * Call this when the connection is re-established to reset stale "unhealthy" state.
 */
export const invalidateHealthCache = (): void => {
  cachedResult = null
  cachedAt = 0
}
