// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ReportTab Component
 *
 * Displays research output in two visual modes:
 *   1. Research Notes (intermediate) -- preview styling with a header badge
 *   2. Final Report -- full-width rendered markdown with export footer
 *
 * Shows streaming indicator when report is being generated.
 * Includes export footer for Markdown and PDF export (final report only).
 */

'use client'

import { type FC, type ReactNode } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { Document } from '@/adapters/ui/icons'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import { useChatStore } from '@/features/chat'
import { ExportFooter } from './ExportFooter'

interface ReportTabProps {
  /** Optional custom content to display instead of store content */
  children?: ReactNode
}

/**
 * Report tab content - displays research output.
 * Subscribes to chat store for report content, category, and streaming state.
 * Renders research notes with a subtle preview treatment and the final report at full prominence.
 */
export const ReportTab: FC<ReportTabProps> = ({ children }) => {
  const { reportContent, reportContentCategory, isStreaming, currentStatus } = useChatStore()

  const reportContentStr = typeof reportContent === 'string' ? reportContent : ''
  const isEmpty = !reportContentStr.trim()
  const isGeneratingReport = isStreaming && currentStatus === 'writing'
  const isResearchNotes = reportContentCategory === 'research_notes'

  return (
    <Flex direction="col" className="h-full">
      {/* Scrollable content area */}
      <Flex direction="col" gap="4" className="flex-1 overflow-y-auto">
        {children ? (
          children
        ) : isEmpty ? (
          <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
            <Document className="text-subtle mb-3 h-8 w-8" />
            <Text kind="body/regular/md" className="text-subtle">
              Report content will appear here when available.
            </Text>
          </Flex>
        ) : isResearchNotes ? (
          /* Research notes: preview treatment */
          <Flex direction="col" gap="3" className="flex-1">
            <Flex
              align="center"
              gap="2"
              className="shrink-0 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 dark:border-yellow-800 dark:bg-yellow-950"
            >
              <div className="h-2 w-2 animate-pulse rounded-full bg-yellow-500" />
              <Text kind="body/regular/sm" className="text-yellow-700 dark:text-yellow-300">
                Research notes from agents — final report is still being generated.
              </Text>
            </Flex>
            <div className="flex-1 opacity-80">
              <MarkdownRenderer
                content={reportContentStr}
                isStreaming={false}
                className="max-w-none"
              />
            </div>
          </Flex>
        ) : (
          /* Final report: full prominence */
          <div className="flex-1">
            <MarkdownRenderer
              content={reportContentStr}
              isStreaming={isGeneratingReport}
              className="max-w-none"
            />
          </div>
        )}
      </Flex>

      {/* Export footer - only meaningful for the final report */}
      <ExportFooter />
    </Flex>
  )
}
