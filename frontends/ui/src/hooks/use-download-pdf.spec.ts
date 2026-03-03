// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act, waitFor } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach, afterEach } from 'vitest'
import { useDownloadPdfRoute } from './use-download-pdf'

describe('useDownloadPdfRoute', () => {
  const originalFetch = global.fetch
  const originalCreateObjectURL = URL.createObjectURL
  const originalRevokeObjectURL = URL.revokeObjectURL

  beforeEach(() => {
    vi.clearAllMocks()

    // Mock URL methods
    global.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    global.URL.revokeObjectURL = vi.fn()
  })

  afterEach(() => {
    global.fetch = originalFetch
    global.URL.createObjectURL = originalCreateObjectURL
    global.URL.revokeObjectURL = originalRevokeObjectURL
    vi.restoreAllMocks()
  })

  test('returns initial state', () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.downloadPdf).toBeInstanceOf(Function)
  })

  test('sets isLoading to true while downloading', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    let resolvePromise: (value: unknown) => void
    const pendingPromise = new Promise((resolve) => {
      resolvePromise = resolve
    })

    global.fetch = vi.fn(() => pendingPromise) as typeof fetch

    // Start download (don't await)
    act(() => {
      result.current.downloadPdf('# Test')
    })

    // Should be loading
    expect(result.current.isLoading).toBe(true)

    // Resolve the promise
    await act(async () => {
      resolvePromise!({
        ok: true,
        blob: () => Promise.resolve(new Blob(['pdf'], { type: 'application/pdf' })),
      })
    })

    // Should stop loading
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
  })

  test('downloads PDF successfully', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    const mockBlob = new Blob(['pdf content'], { type: 'application/pdf' })
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
    })

    // Mock anchor element click - set up AFTER renderHook
    const mockClick = vi.fn()
    const mockAnchor = { href: '', download: '', click: mockClick }
    vi.spyOn(document, 'createElement').mockReturnValue(mockAnchor as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockAnchor as unknown as Node)
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockAnchor as unknown as Node)

    await act(async () => {
      await result.current.downloadPdf('# My Report')
    })

    // Verify fetch was called correctly
    expect(global.fetch).toHaveBeenCalledWith('/api/generate-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown: '# My Report' }),
    })

    // Verify blob URL was created
    expect(URL.createObjectURL).toHaveBeenCalledWith(mockBlob)

    // Verify link was clicked
    expect(mockClick).toHaveBeenCalled()

    // Verify URL was revoked
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')

    // Verify state
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  test('sets download filename with current date when no title provided', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    const mockBlob = new Blob(['pdf content'], { type: 'application/pdf' })
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
    })

    const mockAnchor = { href: '', download: '', click: vi.fn() }
    vi.spyOn(document, 'createElement').mockReturnValue(mockAnchor as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockAnchor as unknown as Node)
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockAnchor as unknown as Node)

    await act(async () => {
      await result.current.downloadPdf('# Test')
    })

    // Verify filename format: report-YYYY-MM-DD.pdf
    expect(mockAnchor.download).toMatch(/^report-\d{4}-\d{2}-\d{2}\.pdf$/)
  })

  test('uses sanitized title as filename when provided', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    const mockBlob = new Blob(['pdf content'], { type: 'application/pdf' })
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
    })

    const mockAnchor = { href: '', download: '', click: vi.fn() }
    vi.spyOn(document, 'createElement').mockReturnValue(mockAnchor as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockAnchor as unknown as Node)
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockAnchor as unknown as Node)

    await act(async () => {
      await result.current.downloadPdf('# Test', 'Market Analysis Report')
    })

    expect(mockAnchor.download).toBe('market-analysis-report.pdf')
  })

  test('handles fetch error', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      statusText: 'Internal Server Error',
    })

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    await act(async () => {
      await result.current.downloadPdf('# Test')
    })

    expect(result.current.error).toBe('Failed to generate PDF: Internal Server Error')
    expect(result.current.isLoading).toBe(false)
    expect(consoleErrorSpy).toHaveBeenCalled()
  })

  test('handles network error', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))

    await act(async () => {
      await result.current.downloadPdf('# Test')
    })

    expect(result.current.error).toBe('Network error')
    expect(result.current.isLoading).toBe(false)
  })

  test('handles non-Error exception', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    global.fetch = vi.fn().mockRejectedValue('Unknown error')

    await act(async () => {
      await result.current.downloadPdf('# Test')
    })

    expect(result.current.error).toBe('Failed to download PDF')
    expect(result.current.isLoading).toBe(false)
  })

  test('clears error on new download attempt', async () => {
    const { result } = renderHook(() => useDownloadPdfRoute())

    // First call fails
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      statusText: 'Error',
    })

    await act(async () => {
      await result.current.downloadPdf('# Test')
    })

    expect(result.current.error).toBe('Failed to generate PDF: Error')

    // Second call succeeds - need to mock document methods
    const mockBlob = new Blob(['pdf content'], { type: 'application/pdf' })
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
    })

    const mockAnchor = { href: '', download: '', click: vi.fn() }
    vi.spyOn(document, 'createElement').mockReturnValue(mockAnchor as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockAnchor as unknown as Node)
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockAnchor as unknown as Node)

    await act(async () => {
      await result.current.downloadPdf('# Test 2')
    })

    // Error should be cleared
    expect(result.current.error).toBeNull()
  })
})
