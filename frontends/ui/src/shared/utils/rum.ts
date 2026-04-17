// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Lightweight Datadog RUM helper.
 *
 * The DD_RUM global is injected by Datadog's browser SDK when configured.
 * The existence check makes every call a no-op in non-Datadog deployments,
 * so this utility is safe to use unconditionally in the public repo.
 */

interface RumApi {
  addError?: (error: Error, context: Record<string, unknown>) => void
}

/**
 * Emit an error event to Datadog RUM.
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
