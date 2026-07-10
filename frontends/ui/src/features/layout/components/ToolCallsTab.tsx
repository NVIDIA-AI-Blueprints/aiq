// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ToolCallsTab Component
 *
 * Sub-tab within ThinkingTab displaying tool calls made during processing.
 *
 * SSE Events: tool.start, tool.end
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { Wrench } from '@/adapters/ui/icons'
import { ToolCallCard, type ToolCallInfo } from './ToolCallCard'
import { EMPTY_RESEARCH_DETAILS_HELP_TEXT } from './research-empty-state-copy'

interface ToolCallsTabProps {
  /** Array of tool call info from SSE events */
  toolCalls?: ToolCallInfo[]
  /** Whether any tool is currently executing */
  isRunning?: boolean
}

/**
 * Tool calls sub-tab content showing tool invocations and results.
 */
export const ToolCallsTab: FC<ToolCallsTabProps> = ({ toolCalls = [] }) => {
  const isEmpty = toolCalls.length === 0
  const runningCount = toolCalls.filter((tc) => tc.status === 'running').length
  const completedCount = toolCalls.filter((tc) => tc.status === 'complete').length

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {/* Header */}
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-subtle">
            Tool Calls
          </Text>
          {toolCalls.length > 0 && (
            <Text kind="body/regular/xs" className="text-subtle">
              {runningCount > 0
                ? `${runningCount} running`
                : `${completedCount}/${toolCalls.length}`}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/xs" className="text-subtle">
          Web searches, file operations, and other tool invocations.
        </Text>
      </Flex>

      {/* Content */}
      {isEmpty ? (
        <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
          <span data-testid="toolcalls-empty-icon" className="text-subtle mb-3 h-8 w-8">
            <Wrench className="h-8 w-8" />
          </span>
          <Text kind="body/regular/md" className="text-subtle">
            No tool calls available.
          </Text>
          <Text kind="body/regular/sm" className="text-subtle mt-2">
            {EMPTY_RESEARCH_DETAILS_HELP_TEXT}
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="2" className="min-h-0 flex-1 overflow-y-auto">
          {toolCalls.map((toolCall) => (
            <div key={toolCall.id} className="shrink-0">
              <ToolCallCard toolCall={toolCall} />
            </div>
          ))}
        </Flex>
      )}
    </Flex>
  )
}
