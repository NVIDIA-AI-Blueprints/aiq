// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * DeepResearchBanner Component
 *
 * Displays status banners for deep research jobs in the chat area.
 * Variants:
 * - "starting": Research in progress, with View Progress action
 * - "success": Research completed, report is ready
 * - "failure": Research failed or was interrupted
 */

'use client'

import { type FC, useCallback } from 'react'
import { Banner, Button, Flex, Text } from '@/adapters/ui'
import { formatTime } from '@/shared/utils/format-time'
import { useLayoutStore } from '@/features/layout/store'
import { useChatStore } from '../store'
import { useLoadJobData } from '../hooks/use-load-job-data'
import type { DeepResearchBannerType } from '../types'

export interface DeepResearchBannerProps {
  /** Type of banner: success or failure */
  bannerType: DeepResearchBannerType
  /** Job ID for identification */
  jobId: string
  /** Total tokens used (for success banner) */
  totalTokens?: number
  /** Number of tool calls (for success banner) */
  toolCallCount?: number
  /** Timestamp of the status update (Date or ISO string from persisted state) */
  timestamp?: Date | string
}

/** Banner status type for KUI Banner component */
type BannerStatus = 'success' | 'info' | 'warning' | 'error'

interface BannerConfig {
  heading: string
  subheading: string
  buttonText: string
  buttonTab: 'report' | 'tasks' | 'thinking'
  status: BannerStatus
}

/** Format token count with K suffix for thousands */
const formatTokens = (count: number): string => {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}K`
  }
  return count.toString()
}

/**
 * Banner configuration for each banner type
 */
const getBannerConfig = (
  bannerType: DeepResearchBannerType,
  jobId: string,
  stats?: { totalTokens?: number; toolCallCount?: number }
): BannerConfig => {
  const jobIdLine = `Job ID: ${jobId}\n`

  switch (bannerType) {
    case 'success': {
      // Build stats suffix for success banner
      const statsParts: string[] = []
      if (stats?.totalTokens && stats.totalTokens > 0) {
        statsParts.push(`${formatTokens(stats.totalTokens)} tokens`)
      }
      if (stats?.toolCallCount && stats.toolCallCount > 0) {
        statsParts.push(`${stats.toolCallCount} tool calls`)
      }
      const statsText = statsParts.length > 0 ? ` (${statsParts.join(' · ')})` : ''

      return {
        heading: `Report Completed!${statsText}`,
        subheading: `Research has finished and a report is ready to view in the research panel. (${jobIdLine})`,
        buttonText: 'View Report',
        buttonTab: 'report',
        status: 'success',
      }
    }
    case 'failure':
      return {
        heading: 'Report Failed to Complete',
        subheading: `Something prevented the research report from completing. Check the thinking for details. (${jobIdLine})`,
        buttonText: 'View Thinking',
        buttonTab: 'thinking',
        status: 'error',
      }
    case 'cancelled':
      return {
        heading: 'Research Cancelled',
        subheading: `Research was stopped by user. You can view any partial progress in the research panel. (${jobIdLine})`,
        buttonText: 'View Progress',
        buttonTab: 'tasks',
        status: 'warning',
      }
    case 'starting':
      return {
        heading: 'Starting Deep Research',
        subheading: `Chat is paused while the report is created to prevent generating multiple reports. You can click away while this runs. This may take several minutes. (${jobIdLine})`,
        buttonText: 'View Progress',
        buttonTab: 'tasks',
        status: 'info',
      }
  }
}

/**
 * Deep research status banner displayed in the chat area
 */
export const DeepResearchBanner: FC<DeepResearchBannerProps> = ({
  bannerType,
  jobId,
  totalTokens,
  toolCallCount,
  timestamp,
}) => {
  const { openRightPanel, setResearchPanelTab } = useLayoutStore()
  const reportContent = useChatStore((state) => state.reportContent)
  const deepResearchStreamLoaded = useChatStore((state) => state.deepResearchStreamLoaded)
  const isDeepResearchStreaming = useChatStore((state) => state.isDeepResearchStreaming)
  const { loadReport, importStreamOnly, isLoading: isStreamLoading } = useLoadJobData()
  const config = getBannerConfig(bannerType, jobId, { totalTokens, toolCallCount })

  // Tabs that require full stream data (tasks, thinking, citations)
  const tabRequiresStream = ['tasks', 'thinking', 'citations'].includes(config.buttonTab)
  
  // Job is complete if banner type indicates completion (success, failure, cancelled)
  // 'starting' banner means job is still in progress - don't try to load archived data
  const isJobComplete = bannerType !== 'starting'

  const handleButtonClick = useCallback(async () => {
    setResearchPanelTab(config.buttonTab)
    openRightPanel('research')
    
    // Only load data for completed jobs
    if (isJobComplete) {
      if (config.buttonTab === 'report' && !reportContent.trim()) {
        // Report tab: load just the report content via REST API
        await loadReport(jobId)
      } else if (tabRequiresStream && !deepResearchStreamLoaded && !isDeepResearchStreaming && !isStreamLoading) {
        // Tasks/Thinking/Citations tabs: load full stream data
        await importStreamOnly(jobId)
      }
    }
    // For incomplete jobs (starting), the live SSE connection is already populating data
  }, [config.buttonTab, openRightPanel, setResearchPanelTab, reportContent, loadReport, jobId, tabRequiresStream, deepResearchStreamLoaded, isDeepResearchStreaming, isStreamLoading, importStreamOnly, isJobComplete])

  // Render action button (same for all banner types)
  const renderActions = () => (
    <Button
      kind="secondary"
      size="small"
      onClick={handleButtonClick}
      aria-label={config.buttonText}
    >
      {config.buttonText}
    </Button>
  )

  return (
    <Flex direction="col" gap="1" className="w-full">
      <Banner
        slotSubheading={config.subheading}
        slotActions={renderActions()}
        kind="header"
        status={config.status}
        actionsPosition="right"
      >
        {config.heading}
      </Banner>
      {timestamp && (
        <Text kind="body/regular/xs" className="text-subtle mr-3 self-end">
          {formatTime(timestamp)}
        </Text>
      )}
    </Flex>
  )
}
