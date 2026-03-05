// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

/**
 * Reactively tracks the user's `prefers-reduced-motion` OS/browser setting.
 * Returns `true` when the user prefers reduced motion, `false` otherwise.
 *
 * Always initialises as `false` so the server and first client render
 * produce identical markup (avoids hydration mismatch). The real value
 * is picked up in a post-mount effect — the brief first paint with
 * transitions enabled is imperceptible since layout hasn't shifted yet.
 */
export function useReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(QUERY)
    setPrefersReduced(mql.matches)
    const handler = (e: MediaQueryListEvent) => setPrefersReduced(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  return prefersReduced
}
