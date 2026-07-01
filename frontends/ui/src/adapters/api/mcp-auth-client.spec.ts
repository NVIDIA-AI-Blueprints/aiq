// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { openAuthPopupAndWait } from './mcp-auth-client'
import type { PerUserAuthStatus } from './data-sources-client'

describe('openAuthPopupAndWait', () => {
  let fakePopup: { closed: boolean; close: ReturnType<typeof vi.fn> }
  let openSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    fakePopup = { closed: false, close: vi.fn(() => { fakePopup.closed = true }) }
    openSpy = vi.fn(() => fakePopup)
    vi.stubGlobal('open', openSpy)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  // The core regression: clicking "Reconnect" starts from an `expired` status, so
  // the first status probe sees `expired`. The popup must stay open through that
  // baseline and only resolve once auth actually completes (`connected`).
  test('does not close on the pre-existing expired status (Reconnect)', async () => {
    const statuses: PerUserAuthStatus[] = ['expired', 'expired', 'connected']
    let i = 0
    const pollStatus = vi.fn(async () => statuses[Math.min(i++, statuses.length - 1)])

    const result = openAuthPopupAndWait('https://provider/auth', 'gdrive', {
      pollStatus,
      pollIntervalMs: 1000,
    })

    // First two probes return the baseline `expired` — popup must remain open.
    await vi.advanceTimersByTimeAsync(1000)
    expect(fakePopup.close).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(fakePopup.close).not.toHaveBeenCalled()

    // Third probe flips to `connected` → resolve as success and close the popup.
    await vi.advanceTimersByTimeAsync(1000)
    await expect(result).resolves.toEqual({ ok: true, sourceId: 'gdrive' })
    expect(fakePopup.close).toHaveBeenCalled()
  })

  test('resolves failure only on a NEW error, not the pre-existing one', async () => {
    // Baseline already `error`; staying `error` must not resolve (it's the state
    // we're trying to fix). A transition expired -> error would, but unchanged
    // error should keep waiting until the popup closes / times out.
    const pollStatus = vi.fn(async (): Promise<PerUserAuthStatus> => 'error')
    const result = openAuthPopupAndWait('https://provider/auth', 'gdrive', {
      pollStatus,
      pollIntervalMs: 1000,
    })

    await vi.advanceTimersByTimeAsync(3000)
    expect(fakePopup.close).not.toHaveBeenCalled()

    // User gives up and closes the popup → resolve empty (caller re-checks status).
    fakePopup.closed = true
    await vi.advanceTimersByTimeAsync(700)
    await expect(result).resolves.toEqual({})
  })

  test('resolves success via callback postMessage from the popup', async () => {
    const result = openAuthPopupAndWait('https://provider/auth', 'gdrive', {})
    // A genuine completion is posted by the callback page via window.opener, so
    // event.source is the popup we opened.
    const evt = new MessageEvent('message', { data: { type: 'mcp-auth', source_id: 'gdrive', ok: true } })
    Object.defineProperty(evt, 'source', { value: fakePopup })
    window.dispatchEvent(evt)
    await expect(result).resolves.toEqual({ ok: true, sourceId: 'gdrive' })
    expect(fakePopup.close).toHaveBeenCalled()
  })

  test('ignores an mcp-auth message from an untrusted source', async () => {
    const result = openAuthPopupAndWait('https://provider/auth', 'gdrive', {})
    // No event.source (a spoofed / cross-window message) must NOT be accepted.
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'mcp-auth', source_id: 'gdrive', ok: true } }))
    // The spoofed message is ignored; the promise only settles when the popup
    // actually closes (empty result), and the popup is never closed by the spoof.
    fakePopup.closed = true
    await vi.advanceTimersByTimeAsync(700)
    await expect(result).resolves.toEqual({})
    expect(fakePopup.close).not.toHaveBeenCalled()
  })

  test('resolves empty when the popup is blocked', async () => {
    openSpy.mockReturnValueOnce(null)
    await expect(openAuthPopupAndWait('https://provider/auth', 'gdrive', {})).resolves.toEqual({})
  })
})
