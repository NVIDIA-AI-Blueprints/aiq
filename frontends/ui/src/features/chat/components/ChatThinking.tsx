// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ChatThinking Component
 *
 * Displays a collapsible panel of intermediate thinking steps from the agent.
 * Shows a status header (spinner while working, check when done) and a flat
 * chronological list of all steps with displayName + timestamp.
 *
 * Uses KUI Collapsible for proper expand/collapse behavior.
 */

'use client'

import { type FC } from 'react'
import { Flex, Text, Collapsible, AnimatedChevron, Spinner } from '@/adapters/ui'
import { CheckCircle, Warning, Clock } from '@/adapters/ui/icons'
import { formatTime } from '@/shared/utils/format-time'
import type { ThinkingStep } from '../types'

export interface ChatThinkingProps {
  /** Array of thinking steps to display */
  steps: ThinkingStep[]
  /** Whether thinking is in progress (shows spinner when true, check when false) */
  isThinking?: boolean
  /** Whether the response was interrupted (page refresh / browser close mid-stream) */
  isInterrupted?: boolean
  /** Whether waiting for user response (HITL prompt pending) */
  isWaiting?: boolean
  /** Data sources that were enabled for this query */
  enabledDataSources?: string[]
  /** Files that were available for this query */
  messageFiles?: Array<{ id: string; fileName: string }>
}

/**
 * Format data source ID to display name
 */
const formatDataSourceName = (sourceId: string): string => {
  // Handle special cases
  if (sourceId === 'web_search') return 'Web Search'
  if (sourceId === 'knowledge_layer') return 'Files'

  // Convert snake_case to Title Case
  return sourceId
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

/**
 * ChatThinking - collapsible thinking steps panel with nvidia green border
 */
export const ChatThinking: FC<ChatThinkingProps> = ({
  steps,
  isThinking = true,
  isInterrupted = false,
  isWaiting = false,
  enabledDataSources = [],
  messageFiles = [],
}) => {
  // Prepare data sources summary (exclude knowledge_layer as we'll show files separately)
  const dataSourcesDisplay = enabledDataSources
    .filter((source) => source !== 'knowledge_layer')
    .map(formatDataSourceName)
    .join(', ')

  const hasDataSources = dataSourcesDisplay.length > 0
  const hasFiles = messageFiles.length > 0

  // Show component if there are steps OR if there are data sources/files to display
  if (steps.length === 0 && !hasDataSources && !hasFiles) {
    return null
  }

  return (
    <div className="bg-surface-sunken border-base w-full rounded-lg border">
      <Collapsible
        slotTrigger={
          <Flex align="center" justify="between" className="w-full cursor-pointer px-4 pt-3" style={{ paddingBottom: 'calc(var(--spacing) * 4)' }}>
            {/* Left: status indicator */}
            <Flex align="center" gap="2">
              {isThinking ? (
                <>
                  <Spinner size="small" aria-label="Thinking in progress" />
                  <Text kind="label/semibold/md" className="text-primary">
                    Working on a response...
                  </Text>
                </>
              ) : isWaiting ? (
                <>
                  <span className="text-brand">
                    <Clock className="h-5 w-5" />
                  </span>
                  <Text kind="label/semibold/md" className="text-primary">
                    Waiting for response
                  </Text>
                </>
              ) : isInterrupted ? (
                <>
                  <span className="text-warning">
                    <Warning className="h-5 w-5" />
                  </span>
                  <Text kind="label/semibold/md" className="text-primary">
                    Interrupted
                  </Text>
                </>
              ) : (
                <>
                  <span className="text-success">
                    <CheckCircle className="h-5 w-5" />
                  </span>
                  <Text kind="label/semibold/md" className="text-primary">
                    Done
                  </Text>
                </>
              )}
            </Flex>

            {/* Right: toggle indicator */}
            <Flex align="center" gap="1">
              <Text kind="label/regular/sm" className="text-secondary">
                {`Show thinking (${steps.length})`}
              </Text>
              <span className="text-secondary">
                <AnimatedChevron />
              </span>
            </Flex>
          </Flex>
        }
      >
        <Flex
          direction="col"
          className="border-base border-t px-4 pb-4 pt-4"
          role="list"
          aria-label="Thinking steps"
        >
          {/* Thinking Steps: 3 levels — Workflow (0) | Function Start/Complete (1) | model/tool (2) */}
          {steps.map((step) => {
            const isWorkflowRoot = step.functionName === 'chat_deepresearcher_agent'
            const isFunctionStep = step.isTopLevel === true
            const indentClass = isWorkflowRoot
              ? ''
              : isFunctionStep
                ? 'pl-4 border-l-2 border-base ml-1'
                : 'pl-8 border-l-2 border-base ml-1'
            return (
              <Flex
                key={step.id}
                align="center"
                justify="between"
                className={`w-full py-1.5 ${indentClass}`}
                role="listitem"
              >
                <Text kind="body/regular/sm" className="text-primary min-w-0 truncate">
                  {step.displayName}
                </Text>
                <Text kind="body/regular/xs" className="text-secondary shrink-0 pl-4">
                  {formatTime(step.timestamp)}
                </Text>
              </Flex>
            )
          })}
        </Flex>
      </Collapsible>

      {/* Data Sources Summary — always visible below the collapsible */}
      {(hasDataSources || hasFiles) && (
        <Flex
          direction="col"
          className="border-base border-t px-4 pt-3"
          style={{ paddingBottom: 'calc(var(--spacing) * 5)' }}
        >
          <Text kind="label/bold/md" className="text-primary mb-1">
            Selected Data Sources:
          </Text>
          {hasDataSources && (
            <Text kind="body/regular/sm" className="text-primary">
              {dataSourcesDisplay}
            </Text>
          )}
          {hasFiles && (
            <Text kind="body/regular/sm" className="text-secondary">
              {messageFiles.map((f) => f.fileName).join(', ')}
            </Text>
          )}
        </Flex>
      )}
    </div>
  )
}
