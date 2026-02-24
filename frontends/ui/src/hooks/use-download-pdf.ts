// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useState } from 'react'

export const useDownloadPdfRoute = () => {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  const downloadPdf = async (markdown: string) => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/generate-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown }),
      })

      if (!response.ok) {
        throw new Error(`Failed to generate PDF: ${response.statusText}`)
      }

      const blob = await response.blob()

      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report-${new Date().toISOString().slice(0, 10)}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)

      URL.revokeObjectURL(url)
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to download PDF'
      setError(errorMessage)
      console.error('PDF download error:', err)
    } finally {
      setIsLoading(false)
    }
  }

  return {
    downloadPdf,
    isLoading,
    error,
    clearError,
  }
}
