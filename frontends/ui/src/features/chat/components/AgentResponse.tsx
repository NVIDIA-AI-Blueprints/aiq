// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentResponse Component
 *
 * Displays a completed agent response in the chat area.
 * Used for short answers that don't need the full report panel.
 * Left-aligned with distinct styling from user messages.
 */

'use client'

import { type FC, useCallback } from 'react'
import { Flex, Text, Button } from '@/adapters/ui'
import { ChevronRight, LoadingSpinner } from '@/adapters/ui/icons'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import { formatTime } from '@/shared/utils/format-time'
import { useLayoutStore } from '@/features/layout/store'
import { useChatStore } from '../store'
import { useLoadJobData } from '../hooks'

export interface AgentResponseProps {
  /** Response content from the agent */
  content: string
  /** Timestamp of the response (Date or ISO string from persisted state) */
  timestamp?: Date | string
  /** Whether to show a button to view the full report */
  showViewReport?: boolean
  /** Display variant - 'default' has box styling, 'inline' has no box (for use inside containers) */
  variant?: 'default' | 'inline'
  /** Deep research job ID for loading report data on-demand */
  jobId?: string
  /** Whether this message has active (streaming) deep research */
  isDeepResearchActive?: boolean
  /** Job status for determining button behavior */
  deepResearchJobStatus?: 'submitted' | 'running' | 'success' | 'failure' | 'interrupted'
}

/**
 * Agent response bubble component for completed responses
 */
export const AgentResponse: FC<AgentResponseProps> = ({
  content,
  timestamp,
  showViewReport = false,
  variant = 'default',
  jobId,
  isDeepResearchActive = false,
  deepResearchJobStatus,
}) => {
  const { openRightPanel, setResearchPanelTab } = useLayoutStore()
  const { reportContent, deepResearchJobId, isDeepResearchStreaming, reconnectToActiveJob, deepResearchStreamLoaded } = useChatStore()
  const { importJobStream, isLoading, error } = useLoadJobData()

  // Determine if we should show the action button
  // Show "View Progress" for active jobs, "View Report" for completed jobs
  const isJobActive = isDeepResearchActive || deepResearchJobStatus === 'submitted' || deepResearchJobStatus === 'running'
  const isJobComplete = deepResearchJobStatus === 'success' || deepResearchJobStatus === 'failure' || deepResearchJobStatus === 'interrupted'
  const shouldShowButton = showViewReport || (jobId && (isJobActive || isJobComplete))
  const buttonText = isJobActive ? 'View Progress' : 'View Report'

  // Check if a different job is currently streaming (in progress)
  const isAnotherJobStreaming = isDeepResearchStreaming && deepResearchJobId && deepResearchJobId !== jobId

  const handleViewReport = useCallback(async () => {
    // For active jobs, ensure stream is connected and open the panel
    if (isJobActive) {
      // Reconnect to active job if not already streaming this job
      if (!isDeepResearchStreaming || deepResearchJobId !== jobId) {
        await reconnectToActiveJob()
      }
      setResearchPanelTab('tasks')
      openRightPanel('research')
      return
    }

    // If another job is actively streaming, just open the panel to show current progress
    // Don't load this report's data as it would interrupt the active research
    if (isAnotherJobStreaming) {
      setResearchPanelTab('tasks')
      openRightPanel('research')
      return
    }

    // For completed jobs, check if we have ALL research data for THIS specific job
    // Important: must verify job ID matches to avoid showing wrong data
    const hasExistingDataForThisJob = 
      jobId && 
      deepResearchJobId === jobId && 
      deepResearchStreamLoaded &&
      reportContent && 
      reportContent.trim().length > 0

    if (hasExistingDataForThisJob) {
      setResearchPanelTab('report')
      openRightPanel('research')
      return
    }

    // Fetch ALL research data from backend (report + citations + tasks + tool calls + agents + files)
    // This is necessary because localStorage no longer stores heavy research data
    if (jobId) {
      await importJobStream(jobId)
    } else {
      setResearchPanelTab('report')
      openRightPanel('research')
    }
  }, [jobId, deepResearchJobId, reportContent, deepResearchStreamLoaded, isJobActive, isAnotherJobStreaming, isDeepResearchStreaming, importJobStream, reconnectToActiveJob, setResearchPanelTab, openRightPanel])

  // Guard against null, undefined, empty, or literal "null" string content
  // This includes deep research tracking messages which have empty content
  // (the 'starting' banner is now a separate message handled by DeepResearchBanner)
  if (!content || !content.trim() || content === 'null') {
    return null
  }

  // Inline variant - no box styling (for use inside containers like thinking process)
  if (variant === 'inline') {
    return (
      <Flex direction="col" gap="2" className="w-full break-words overflow-hidden">
        {/* Response Content rendered as markdown */}
        <MarkdownRenderer content={content} />

        {/* Optional action button */}
        {shouldShowButton && (
          <Flex align="center" justify="end" className="mt-1">
            <Button
              kind="tertiary"
              size="tiny"
              onClick={handleViewReport}
              disabled={isLoading}
              aria-label={isLoading ? 'Loading...' : buttonText}
              title={error ? `Error: ${error}` : isLoading ? 'Loading...' : buttonText}
            >
              <Flex align="center" gap="1">
                {isLoading ? (
                  <>
                    <LoadingSpinner size="small" aria-label="Loading" className="h-3 w-3" />
                    <Text kind="label/regular/xs">Loading...</Text>
                  </>
                ) : (
                  <>
                    <Text kind="label/regular/xs">{buttonText}</Text>
                    <ChevronRight className="h-3 w-3" aria-hidden="true" />
                  </>
                )}
              </Flex>
            </Button>
          </Flex>
        )}

        {/* Timestamp outside content, right-aligned */}
        {timestamp && (
          <Text kind="body/regular/xs" className="text-subtle mt-1 mr-3 self-end">
            {formatTime(timestamp)}
          </Text>
        )}
      </Flex>
    )
  }

  // Default variant - with box styling
  return (
    <Flex justify="start" className="w-full">
      <Flex direction="col" className="max-w-[85%]">
        <Flex
          direction="col"
          gap="2"
          className="bg-surface-sunken-opaque border-base rounded-br-xl rounded-tl-xl rounded-tr-xl border p-4 break-words overflow-hidden"
        >
          {/* Response Content rendered as markdown */}
          <MarkdownRenderer content={content} />

          {/* Optional action button stays inside the bubble */}
          {shouldShowButton && (
            <Flex align="center" justify="end" className="mt-1">
              <Button
                kind="tertiary"
                size="tiny"
                onClick={handleViewReport}
                disabled={isLoading}
                aria-label={isLoading ? 'Loading...' : buttonText}
                title={error ? `Error: ${error}` : isLoading ? 'Loading...' : buttonText}
              >
                <Flex align="center" gap="1">
                  {isLoading ? (
                    <>
                      <LoadingSpinner size="small" aria-label="Loading" className="h-3 w-3" />
                      <Text kind="label/regular/xs">Loading...</Text>
                    </>
                  ) : (
                    <>
                      <Text kind="label/regular/xs">{buttonText}</Text>
                      <ChevronRight className="h-3 w-3" aria-hidden="true" />
                    </>
                  )}
                </Flex>
              </Button>
            </Flex>
          )}
        </Flex>

        {/* Timestamp outside bubble, right-aligned */}
        {timestamp && (
          <Text kind="body/regular/xs" className="text-subtle mt-1 mr-3 self-end">
            {formatTime(timestamp)}
          </Text>
        )}
      </Flex>
    </Flex>
  )
}
