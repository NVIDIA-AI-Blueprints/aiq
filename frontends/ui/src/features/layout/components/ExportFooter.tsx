// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ExportFooter Component
 *
 * Footer with export actions for reports.
 * Provides buttons to export content as Markdown or PDF.
 */

'use client'

import { type FC, useCallback, useState } from 'react'
import { Banner, Flex, Button } from '@/adapters/ui'
import { useChatStore, useIsCurrentSessionBusy } from '@/features/chat'
import { downloadAsMarkdown } from '@/utils/download-as-markdown'
import { useDownloadPdfRoute } from '@/hooks/use-download-pdf'
import { Download } from '@/adapters/ui/icons'

interface ExportFooterProps {
  /** Whether to disable export buttons (e.g., when no content) */
  disabled?: boolean
}

/**
 * Export footer with Markdown and PDF export buttons.
 * Only renders when there's content to export.
 */
export const ExportFooter: FC<ExportFooterProps> = ({ disabled }) => {
  const reportContent = useChatStore((state) => state.reportContent)
  const { downloadPdf, isLoading: isPdfLoading, error: pdfError, clearError: clearPdfError } = useDownloadPdfRoute()
  const [mdError, setMdError] = useState<string | null>(null)

  // Defensive check: ensure reportContent is a string before calling trim()
  const reportContentStr = typeof reportContent === 'string' ? reportContent : ''
  const hasContent = reportContentStr.trim().length > 0

  // Uses centralized hook that checks BOTH ephemeral AND persisted state.
  // This survives page refresh: even if SSE ephemeral flags are lost,
  // the hook derives busy state from persisted message history.
  const isDeepResearchInProgress = useIsCurrentSessionBusy()

  const isExportDisabled = disabled || !hasContent || isDeepResearchInProgress

  const tooltipContent = isDeepResearchInProgress
    ? 'Export will be available when research is complete'
    : hasContent
      ? 'Export report'
      : 'No content to export'

  const handleExportMarkdown = useCallback(() => {
    if (isExportDisabled) return
    setMdError(null)
    const result = downloadAsMarkdown(reportContentStr)
    if (!result.success && result.error) {
      setMdError(result.error)
    }
  }, [isExportDisabled, reportContentStr])

  const handleExportPDF = useCallback(() => {
    if (isExportDisabled || isPdfLoading) return
    downloadPdf(reportContentStr)
  }, [isExportDisabled, isPdfLoading, reportContentStr, downloadPdf])

  const exportError = mdError || pdfError
  const clearExportError = useCallback(() => {
    setMdError(null)
    clearPdfError()
  }, [clearPdfError])

  return (
    <Flex direction="col" className="border-base shrink-0 border-t">
      {exportError && (
        <Banner kind="inline" status="error" onClose={clearExportError} className="mx-4 mt-3">
          {exportError}
        </Banner>
      )}
      <Flex align="center" justify="end" gap="2" className="px-4 py-3">
        <Button
          kind="tertiary"
          size="small"
          onClick={handleExportMarkdown}
          disabled={isExportDisabled}
          aria-label={isExportDisabled ? `Export as Markdown (${tooltipContent})` : 'Export as Markdown'}
          title={tooltipContent}
        >
          <Download />
          Markdown
        </Button>
        <Button
          kind="primary"
          color="brand"
          size="small"
          onClick={handleExportPDF}
          disabled={isExportDisabled || isPdfLoading}
          aria-label={
            isPdfLoading
              ? 'Generating PDF...'
              : isExportDisabled
                ? `Export as PDF (${tooltipContent})`
                : 'Export as PDF'
          }
          title={isPdfLoading ? 'Generating PDF...' : tooltipContent}
        >
          <Download />
          {isPdfLoading ? 'Generating...' : 'PDF'}
        </Button>
      </Flex>
    </Flex>
  )
}
