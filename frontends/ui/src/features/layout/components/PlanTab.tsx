// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * PlanTab Component
 *
 * Tab displaying the research planning process including:
 * - Clarification questions from the agent
 * - Research plan previews
 * - User responses
 *
 * Receives system_interaction_message events routed from WebSocket.
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { Document } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Plan tab content showing clarification questions and plan previews.
 * Subscribes to planMessages from the chat store.
 */
export const PlanTab: FC = () => {
  const { planMessages, isStreaming, isLoading } = useChatStore()

  const isEmpty = planMessages.length === 0
  const isActive = isStreaming || isLoading

  return (
    <Flex direction="col" gap="4" className="h-full">
      {/* Process Overview */}
      <Flex direction="col" gap="2">
        <Text kind="label/semibold/md" className="text-primary">
          Process Overview
        </Text>
        <Text kind="body/regular/sm" className="text-subtle">
         Once the research <b>plan</b> is approved, a <b>task</b> list will be generated. Agents will
          asynchronously <b>think</b> on these tasks using sources and tools as needed. Found sources will be
          continuously appended to <b>citations</b>. Once enough information is found, report drafts will be
          generated and edited. Then citations will  go through validation and verification, until a final <b>report</b> is ready and available for export.
        </Text>
      </Flex>

      {/* Header */}
      <Flex align="center" justify="between">
        <Text kind="label/semibold/md" className="text-subtle">
          Research Plan
        </Text>
        {isActive && (
          <Text kind="body/regular/xs" className="text-subtle">
            Planning...
          </Text>
        )}
      </Flex>

      {/* Content */}
      {isEmpty ? (
        <Flex
          direction="col"
          align="center"
          justify="center"
          className="flex-1 text-center py-8"
        >
          <span data-testid="plantab-empty-icon" className="text-subtle mb-3 h-8 w-8">
            <Document className="h-8 w-8" />
          </span>
          <Text kind="body/regular/md" className="text-subtle">
            The research plan will appear here once deep research begins.
          </Text>
          <Text kind="body/regular/sm" className="text-subtle mt-2">
            Plans show clarification questions, research outline, and sections.
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="4" className="min-h-0 flex-1 overflow-y-auto">
          {planMessages.map((message) => (
            <Flex
              key={message.id}
              direction="col"
              gap="2"
              className="shrink-0 rounded-lg border bg-surface-sunken border-base p-4"
            >
              {/* Message header with timestamp */}
              <Flex align="center" justify="between" className="mb-1">
                <Text kind="label/semibold/xs" className="text-subtle uppercase">
                  {message.inputType === 'approval' ? 'Plan Preview' : 'Agent'}
                </Text>
                <Text kind="body/regular/xs" className="text-subtle">
                  {formatTime(message.timestamp)}
                </Text>
              </Flex>

              {/* Message content - render as markdown */}
              <div className="prose prose-sm prose-invert max-w-none">
                <MarkdownRenderer content={message.text} />
              </div>

              {/* User response if provided */}
              {message.userResponse && (
                <Flex direction="col" gap="1" className="mt-3 pt-3 border-t border-base">
                  <Text kind="label/semibold/xs" className="text-subtle uppercase">
                    Your Response
                  </Text>
                  <Text kind="body/regular/sm" className="text-primary">
                    {message.userResponse}
                  </Text>
                </Flex>
              )}
            </Flex>
          ))}
        </Flex>
      )}
    </Flex>
  )
}
