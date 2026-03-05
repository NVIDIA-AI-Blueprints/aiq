// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { sanitizeFilename } from './sanitize-filename'

interface DownloadResult {
  success: boolean
  error?: string
}

export const downloadAsMarkdown = (data: string, filename?: string): DownloadResult => {
  try {
    const blob = new Blob([data], { type: 'text/markdown;charset=utf-8' })

    const baseName = filename
      ? sanitizeFilename(filename)
      : `report-${new Date().toISOString().slice(0, 10)}`

    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.style.display = 'none'
    a.href = url
    a.download = `${baseName}.md`

    document.body.appendChild(a)
    a.click()

    setTimeout(() => {
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    }, 100)

    return { success: true }
  } catch (error) {
    console.error('Error downloading markdown:', error)
    return { success: false, error: 'Failed to download report as Markdown.' }
  }
}
