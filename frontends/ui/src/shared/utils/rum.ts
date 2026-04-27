// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Lightweight RUM (Real User Monitoring) helper.
 *
 * The DD_RUM global is injected by a deployment overlay's browser SDK
 * (e.g. Datadog RUM). The existence check makes every call a no-op in
 * non-instrumented deployments, so this utility is safe to use
 * unconditionally in the public repo.
 */

interface RumApi {
  addError?: (error: Error, context: Record<string, unknown>) => void
  addAction?: (name: string, context: Record<string, unknown>) => void
}

/**
 * Emit an error event to RUM — use for unexpected failures.
 * No-op when the RUM SDK is not loaded or when called server-side.
 *
 * @param message - Human-readable error description
 * @param context - Structured context fields (appear as facets in RUM Explorer)
 */
export const trackRumError = (message: string, context: Record<string, unknown> = {}): void => {
  if (typeof window === 'undefined') return
  const ddRum = (window as unknown as Record<string, unknown>).DD_RUM as RumApi | undefined
  ddRum?.addError?.(new Error(message), { source: 'custom', ...context })
}

/**
 * Emit an action event to RUM — use for expected/informational events.
 * No-op when the RUM SDK is not loaded or when called server-side.
 *
 * @param name - Action name (appears in the RUM Actions tab)
 * @param context - Structured context fields (appear as facets in RUM Explorer)
 */
export const trackRumAction = (name: string, context: Record<string, unknown> = {}): void => {
  if (typeof window === 'undefined') return
  const ddRum = (window as unknown as Record<string, unknown>).DD_RUM as RumApi | undefined
  ddRum?.addAction?.(name, context)
}

// --- Auth-specific helpers ---

/** Auth error codes that represent expected lifecycle events, not bugs. */
const EXPECTED_AUTH_CODES = new Set(['token_missing', 'token_expired', 'session_refresh_failed'])

/**
 * Route an auth event to the appropriate RUM channel based on the error code.
 * Expected codes (token expiration, session refresh) → action (informational).
 * Unexpected codes (invalid token, unknown) → error (alertable).
 *
 * @param code - The auth error code from the backend or session layer
 * @param context - Additional context fields for the RUM event
 */
export const trackAuthEvent = (code: string, context: Record<string, unknown> = {}): void => {
  const enriched = { auth_error_code: code, ...context }
  if (EXPECTED_AUTH_CODES.has(code)) {
    trackRumAction(`Auth: ${code}`, enriched)
  } else {
    trackRumError(`Auth: ${code}`, enriched)
  }
}
