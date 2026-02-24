// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ReportCard Component
 *
 * Card displaying report content with markdown rendering and export functionality.
 * Integrates export actions (Markdown, PDF) from ExportFooter functionality.
 *
 * SSE Events:
 * - artifact.update where data.type === 'output': Final report content
 * - artifact.update where data.type === 'file': Draft file content
 */

'use client'

import { type FC, useCallback } from 'react'
import { Flex, Text, Button } from '@/adapters/ui'
import { Download, Document } from '@/adapters/ui/icons'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import { downloadAsMarkdown } from '@/utils/download-as-markdown'
import { useDownloadPdfRoute } from '@/hooks/use-download-pdf'
import { useIsCurrentSessionBusy } from '@/features/chat'

interface ReportCardProps {
  /** Report content in markdown format */
  content: string
  /** Report title */
  title?: string
  /** Whether this is a draft or final version */
  isDraft?: boolean
  /** Whether content is still streaming (deprecated - now checked via store) */
  isStreaming?: boolean
}

/**
 * Calculate word count from content
 */
const getWordCount = (content: string): number => {
  return content.trim().split(/\s+/).filter(Boolean).length
}

/**
 * Card showing report content with export controls.
 */
export const ReportCard: FC<ReportCardProps> = ({
  content,
  title,
  isDraft = false,
  isStreaming: _isStreaming = false, // Deprecated - kept for backward compatibility but not used
}) => {
  const { downloadPdf, isLoading: isPdfLoading } = useDownloadPdfRoute()

  const hasContent = content.trim().length > 0
  const wordCount = hasContent ? getWordCount(content) : 0

  // Uses centralized hook that checks BOTH ephemeral AND persisted state.
  // This survives page refresh: even if SSE ephemeral flags are lost,
  // the hook derives busy state from persisted message history.
  const isDeepResearchInProgress = useIsCurrentSessionBusy()

  const isExportDisabled = !hasContent || isDeepResearchInProgress

  const tooltipContent = isDeepResearchInProgress
    ? 'Export will be available when research is complete'
    : hasContent
      ? 'Export report'
      : 'No content to export'

  const handleExportMarkdown = useCallback(() => {
    if (isExportDisabled) return
    downloadAsMarkdown(content)
  }, [isExportDisabled, content])

  const handleExportPDF = useCallback(() => {
    if (isExportDisabled || isPdfLoading) return
    downloadPdf(content)
  }, [isExportDisabled, isPdfLoading, content, downloadPdf])

  if (!hasContent) {
    return (
      <Flex
        direction="col"
        align="center"
        justify="center"
        className="h-full text-center py-8"
      >
        <Document className="text-subtle mb-3 h-8 w-8" />
        <Text kind="body/regular/md" className="text-subtle">
          The report will appear here once research is complete.
        </Text>
        <Text kind="body/regular/sm" className="text-subtle mt-2">
          You can export it as Markdown or PDF.
        </Text>
      </Flex>
    )
  }

  return (
    <Flex direction="col" className="h-full">
      {/* Header */}
      <Flex align="center" justify="between" className="mb-4 shrink-0">
        <Flex align="center" gap="2">
          {title && <Text kind="label/semibold/md">{title}</Text>}
          {isDraft && (
            <Text kind="label/regular/xs" className="text-warning bg-warning/10 px-2 py-0.5 rounded">
              Draft
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/xs" className="text-subtle">
          {wordCount.toLocaleString()} words
        </Text>
      </Flex>

      {/* Content */}
      <div className="flex-1 overflow-y-auto pr-2">
        <MarkdownRenderer content={content} />
      </div>

      {/* Export Footer */}
      <Flex align="center" justify="end" gap="2" className="border-base shrink-0 border-t pt-3 mt-4">
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
