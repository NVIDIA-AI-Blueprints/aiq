// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Connection Recovery Hook
 *
 * Activates only when connection error cards are visible in the store.
 * Uses exponential backoff health polling + browser online/visibility
 * events to detect backend recovery, then auto-dismisses error cards
 * and invokes a recovery callback (typically WebSocket reconnect).
 *
 * Zero overhead when healthy: no timers, no listeners.
 */

'use client'

import { useCallback, useEffect, useRef } from 'react'
import {
  checkBackendHealthCached,
  invalidateHealthCache,
} from '@/shared/hooks/use-backend-health'
import { useChatStore, selectHasConnectionError } from '../store'

const INITIAL_DELAY_MS = 5_000
const MAX_DELAY_MS = 60_000
const BACKOFF_FACTOR = 2

/**
 * Poll for backend recovery when connection errors are shown.
 *
 * @param onRecovered - Called once when the backend is confirmed healthy
 *   (e.g. trigger WebSocket reconnect).
 */
export function useConnectionRecovery(onRecovered: () => void): void {
  const hasConnectionError = useChatStore(selectHasConnectionError)
  const dismissConnectionErrors = useChatStore(
    (s) => s.dismissConnectionErrors
  )

  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const delayRef = useRef(INITIAL_DELAY_MS)
  const activeRef = useRef(false)

  const checkHealth = useCallback(async () => {
    invalidateHealthCache()
    const healthy = await checkBackendHealthCached()

    if (!activeRef.current) return

    if (healthy) {
      activeRef.current = false
      dismissConnectionErrors()
      onRecovered()
      return
    }

    delayRef.current = Math.min(
      delayRef.current * BACKOFF_FACTOR,
      MAX_DELAY_MS
    )
    timerRef.current = setTimeout(checkHealth, delayRef.current)
  }, [dismissConnectionErrors, onRecovered])

  // Activate / deactivate polling based on connection error presence
  useEffect(() => {
    if (!hasConnectionError) {
      activeRef.current = false
      delayRef.current = INITIAL_DELAY_MS
      clearTimeout(timerRef.current)
      return
    }

    activeRef.current = true
    delayRef.current = INITIAL_DELAY_MS
    timerRef.current = setTimeout(checkHealth, delayRef.current)

    return () => {
      activeRef.current = false
      clearTimeout(timerRef.current)
    }
  }, [hasConnectionError, checkHealth])

  // Browser event triggers — check immediately when network comes back or tab refocuses
  useEffect(() => {
    if (!hasConnectionError) return

    const onOnline = () => {
      delayRef.current = INITIAL_DELAY_MS
      checkHealth()
    }

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        checkHealth()
      }
    }

    window.addEventListener('online', onOnline)
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      window.removeEventListener('online', onOnline)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [hasConnectionError, checkHealth])
}
