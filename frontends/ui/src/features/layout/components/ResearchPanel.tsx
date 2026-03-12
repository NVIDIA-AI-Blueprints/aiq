// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ResearchPanel Component
 *
 * Right-side panel showing Thinking, Citations, or Report content.
 * Includes top action bar with tabs.
 *
 * This panel PUSHES the chat area (takes 60% width) rather than overlaying it.
 */

'use client'

import { type FC, type ReactNode, useCallback, useRef, useEffect } from 'react'
import { Flex, Button, SegmentedControl, Spinner, Text } from '@/adapters/ui'
import { Close, Generate, StopCircle } from '@/adapters/ui/icons'
import { cancelJob } from '@/adapters/api'
import { useChatStore, useLoadJobData } from '@/features/chat'
import { useAuth } from '@/adapters/auth'
import { useReducedMotion } from '@/hooks/use-reduced-motion'
import { useLayoutStore } from '../store'
import { PlanTab } from './PlanTab'
import { TasksTab } from './TasksTab'
import { ThinkingTab } from './ThinkingTab'
import { CitationsTab } from './CitationsTab'
import { ReportTab } from './ReportTab'
import type { ResearchPanelTab } from '../types'

const TABS_REQUIRING_STREAM: ResearchPanelTab[] = ['tasks', 'thinking', 'citations']

/** Fallback timeout: if the SSE stream doesn't deliver the interrupted
 *  status within this window after cancel, clean up the UI optimistically. */
const CANCEL_FALLBACK_TIMEOUT_MS = 5000

interface ResearchPanelProps {
  /** Content to display in the panel */
  children?: ReactNode
  /** Whether the user is authenticated */
  isAuthenticated?: boolean
}

/**
 * Research panel with tabbed content (Thinking, Citations, Report).
 * Opens from the right side of the screen, pushing the chat area.
 * Takes 60% of the screen width when open.
 */
export const ResearchPanel: FC<ResearchPanelProps> = ({ children, isAuthenticated = false }) => {
  const { rightPanel, researchPanelTab, setResearchPanelTab, closeRightPanel, openRightPanel } = useLayoutStore()
  const isDeepResearchStreaming = useChatStore((state) => state.isDeepResearchStreaming)
  const deepResearchJobId = useChatStore((state) => state.deepResearchJobId)
  const deepResearchStreamLoaded = useChatStore((state) => state.deepResearchStreamLoaded)
  const { importStreamOnly, isLoading: isStreamLoading } = useLoadJobData()
  const { idToken } = useAuth()

  const prefersReducedMotion = useReducedMotion()

  const isOpen = rightPanel === 'research'
  const cancelFallbackRef = useRef<NodeJS.Timeout | null>(null)

  // Clean up cancel fallback timer on unmount
  useEffect(() => {
    return () => {
      if (cancelFallbackRef.current) {
        clearTimeout(cancelFallbackRef.current)
        cancelFallbackRef.current = null
      }
    }
  }, [])

  const handleClose = useCallback(() => {
    closeRightPanel()
  }, [closeRightPanel])

  const handleStopResearch = useCallback(async () => {
    if (!deepResearchJobId) return
    const cancelledJobId = deepResearchJobId
    try {
      await cancelJob(cancelledJobId, idToken || undefined)

      // Fallback: if the SSE stream is broken or stalled and the
      // useDeepResearch hook's onJobStatus never receives the
      // "interrupted" event, clean up locally after a grace period.
      // This is a safety net in addition to the hook's own fallback.
      if (cancelFallbackRef.current) clearTimeout(cancelFallbackRef.current)
      cancelFallbackRef.current = setTimeout(() => {
        cancelFallbackRef.current = null
        const state = useChatStore.getState()
        if (!state.isDeepResearchStreaming || state.deepResearchJobId !== cancelledJobId) {
          return // Already cleaned up by SSE or hook fallback
        }
        console.warn(
          '[ResearchPanel] Cancel fallback: SSE did not deliver interrupted status. Cleaning up locally.'
        )
        state.stopAllDeepResearchSpinners()
        const ownerConvId = state.deepResearchOwnerConversationId
        const messageId = state.activeDeepResearchMessageId
        const hasReport = Boolean(state.reportContent?.trim())
        if (ownerConvId && messageId) {
          state.patchConversationMessage(ownerConvId, messageId, {
            content: '',
            deepResearchJobStatus: 'interrupted',
            isDeepResearchActive: false,
            showViewReport: hasReport,
          })
        }
        state.addDeepResearchBanner('cancelled', cancelledJobId, ownerConvId || undefined)
        state.completeDeepResearch()
        state.setStreaming(false)
      }, CANCEL_FALLBACK_TIMEOUT_MS)
    } catch (error) {
      console.error('Failed to cancel job:', error)
    }
  }, [deepResearchJobId, idToken])

  const handleToggle = useCallback(() => {
    if (!isAuthenticated) return

    if (isOpen) {
      closeRightPanel()
    } else {
      openRightPanel('research')

      // Trigger stream import when opening panel if current tab requires it and data not loaded
      if (
        TABS_REQUIRING_STREAM.includes(researchPanelTab) &&
        deepResearchJobId &&
        !deepResearchStreamLoaded &&
        !isDeepResearchStreaming &&
        !isStreamLoading
      ) {
        void importStreamOnly(deepResearchJobId)
      }
    }
  }, [isAuthenticated, isOpen, closeRightPanel, openRightPanel, researchPanelTab, deepResearchJobId, deepResearchStreamLoaded, isDeepResearchStreaming, isStreamLoading, importStreamOnly])

  const handleTabChange = useCallback(
    (value: string) => {
      const tab = value as ResearchPanelTab
      setResearchPanelTab(tab)

      // Trigger stream import when clicking Tasks/Thinking/Citations for a loaded (non-streaming) job
      if (
        TABS_REQUIRING_STREAM.includes(tab) &&
        deepResearchJobId &&
        !deepResearchStreamLoaded &&
        !isDeepResearchStreaming &&
        !isStreamLoading
      ) {
        // Fire and forget - don't block the tab change
        void importStreamOnly(deepResearchJobId)
      }
    },
    [setResearchPanelTab, deepResearchJobId, deepResearchStreamLoaded, isDeepResearchStreaming, isStreamLoading, importStreamOnly]
  )

  return (
    // Wrapper: uses flex to keep button visible while panel animates
    <div
      className="relative h-full flex"
      style={{
        width: isOpen ? 'calc(60% + 40px)' : '40px',
        minWidth: isOpen ? 'calc(60% + 40px)' : '40px',
        transition: prefersReducedMotion
          ? 'none'
          : 'width 600ms ease-in-out, min-width 600ms ease-in-out',
      }}
    >
      {/* Toggle Tag Button - protruding from left side, always visible */}
      <button
        onClick={handleToggle}
        disabled={!isAuthenticated}
        className={`research-panel-toggle border-base bg-surface-base relative z-10 flex w-10 shrink-0 items-center justify-center self-start overflow-hidden mt-[calc(var(--spacing)*3)] rounded-l-lg border-b border-l border-r border-t transition-colors ${
          isAuthenticated ? 'cursor-pointer hover:border-[#76B900]' : 'cursor-not-allowed opacity-50'
        }`}
        style={{ height: 'calc(var(--spacing) * 38)' }}
        aria-label={isOpen ? 'Close research panel' : 'Open research panel'}
        aria-expanded={isOpen}
        title={isAuthenticated ? (isOpen ? 'Close research panel' : 'Open research panel') : 'Sign in to access research panel'}
        data-testid="research-panel-toggle"
      >
        <span
          className="absolute left-1/2 -translate-x-1/2 flex items-center justify-center"
          style={{ top: 'calc(var(--spacing) * 3)', width: 'calc(var(--spacing) * 6)', height: 'calc(var(--spacing) * 6)' }}
        >
          {isDeepResearchStreaming ? (
            <Spinner size="small" aria-label="Researching" />
          ) : (
            <Generate className="h-[calc(var(--spacing)*6)] w-[calc(var(--spacing)*6)]" />
          )}
        </span>
        <Text
          kind="label/semibold/sm"
          className="absolute left-1/2 -translate-x-1/2 -rotate-90 whitespace-nowrap text-primary"
          style={{ top: 'calc(var(--spacing) * 21)' }}
        >
          Show Research
        </Text>
      </button>

      {/* Outer container: clips content, fills remaining space */}
      <div
        className="border-base bg-surface-base h-full flex-1 overflow-hidden rounded-tl-xl border-l border-t -ml-px"
        aria-hidden={!isOpen}
      >
        {/* Inner container: fixed width so content stays stable */}
        <Flex
          direction="col"
          className="h-full w-full"
          style={{
            visibility: isOpen ? 'visible' : 'hidden',
            opacity: isOpen ? 1 : 0,
            transition: prefersReducedMotion
              ? 'none'
              : isOpen
                ? 'opacity 100ms ease-in-out, visibility 0ms'
                : 'opacity 100ms ease-in-out 500ms, visibility 0ms 600ms',
          }}
        >
        {/* Header with tabs and close button */}
        <Flex align="center" justify="between" className="border-base shrink-0 border-b pl-6 pr-8 py-4">
          <Flex align="center" gap="density-xl">
            <SegmentedControl
              value={researchPanelTab}
              onValueChange={handleTabChange}
              size="medium"
              items={[
                { value: 'plan', children: 'Plan' },
                { value: 'tasks', children: 'Tasks' },
                { value: 'thinking', children: 'Thinking' },
                { value: 'citations', children: 'Citations' },
                { value: 'report', children: 'Report' },
              ]}
            />
            {/* Stop Researching button - always visible, disabled when not streaming */}
            <Button
              kind="tertiary"
              size="small"
              onClick={isDeepResearchStreaming ? handleStopResearch : undefined}
              disabled={!isDeepResearchStreaming}
              aria-label="Stop researching"
              title={isDeepResearchStreaming ? 'Stop researching' : 'No active research'}
              data-testid="research-panel-stop"
            >
              <StopCircle className="h-4 w-4 mr-2" aria-hidden="true" />
              Stop Researching
            </Button>
          </Flex>
          <Flex align="center" gap="density-xl">
            {/* Close button */}
            <Button
              kind="tertiary"
              size="small"
              onClick={handleClose}
              aria-label="Close research panel"
              title="Close research panel"
              data-testid="research-panel-close"
            >
              <Close className="h-4 w-4" aria-hidden="true" />
            </Button>
          </Flex>
        </Flex>

        {/* Content Area - each tab manages its own scrolling and footer */}
        <Flex direction="col" className="flex-1 overflow-hidden py-5 pl-6 pr-8">
          {isStreamLoading ? (
            <Flex direction="col" align="center" justify="center" className="h-full gap-4">
              <Spinner size="medium" aria-label="Loading research data" />
              <Text kind="body/regular/md" className="text-tertiary">
                {TABS_REQUIRING_STREAM.includes(researchPanelTab)
                  ? 'Loading research data...'
                  : 'Loading report...'}
              </Text>
            </Flex>
          ) : (
            <>
              {researchPanelTab === 'plan' && <PlanTab />}
              {researchPanelTab === 'tasks' && <TasksTab />}
              {researchPanelTab === 'thinking' && <ThinkingTab />}
              {researchPanelTab === 'citations' && <CitationsTab />}
              {researchPanelTab === 'report' && <ReportTab>{children}</ReportTab>}
            </>
          )}
        </Flex>
      </Flex>
      </div>
    </div>
  )
}
