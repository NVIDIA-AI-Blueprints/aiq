// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ToolCallCard Component
 *
 * Expandable card displaying a single tool invocation with its name, arguments, and result.
 *
 * SSE Events:
 * - tool.start: Creates card with tool name and input arguments
 * - tool.end: Updates card with result/output
 */

'use client'

import { type FC, useState } from 'react'
import { Flex, Text, Button } from '@/adapters/ui'
import { ChevronDown, Check, Close, Clock, LoadingSpinner } from '@/adapters/ui/icons'

/** Tool call information from SSE events */
export interface ToolCallInfo {
  /** Unique identifier for this tool call */
  id: string
  /** Tool name (e.g., "tavily_web_search", "write_file") */
  name: string
  /** Tool input arguments */
  arguments?: Record<string, unknown>
  /** Tool output/result (after tool.end) */
  result?: string
  /** Current execution status */
  status: 'pending' | 'running' | 'complete' | 'error'
  /** When tool was called */
  timestamp?: Date | string
  /** Parent agent that invoked the tool */
  workflow?: string
  /** Error message if status is error */
  error?: string
}

interface ToolCallCardProps {
  /** Tool call information */
  toolCall: ToolCallInfo
}

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Format tool arguments for display.
 *
 * Handles the _raw/_truncated sentinel created by normalizeToolInput in the
 * adapter layer. When the backend trims a large tool input via Python str(),
 * the adapter wraps the repr string in { _raw, _truncated }. This function
 * detects that sentinel and displays the raw string directly instead of
 * double-quoting it through JSON.stringify.
 */
const formatArguments = (args: Record<string, unknown>, pretty = false): string => {
  if ('_raw' in args && typeof args._raw === 'string') {
    return args._raw
  }
  return pretty ? JSON.stringify(args, null, 2) : JSON.stringify(args)
}

/**
 * Get preview text for collapsed state
 */
const getPreviewText = (toolCall: ToolCallInfo): string => {
  if (toolCall.arguments) {
    const formatted = formatArguments(toolCall.arguments)
    return formatted.length > 100 ? `${formatted.substring(0, 100)}...` : formatted
  }
  return ''
}

/**
 * Expandable card showing a tool call's details.
 */
export const ToolCallCard: FC<ToolCallCardProps> = ({ toolCall }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const isRunning = toolCall.status === 'running'
  const isComplete = toolCall.status === 'complete'
  const isError = toolCall.status === 'error'

  // Disable expansion while running (content is still being populated)
  const canExpand = !isRunning

  // Determine text color based on status
  const textColor = isRunning
    ? 'var(--text-color-feedback-info)'
    : isComplete
      ? 'var(--text-color-feedback-success)'
      : isError
        ? 'var(--text-color-feedback-danger)'
        : 'var(--text-color-subtle)'

  const previewText = getPreviewText(toolCall)
  const hasPreview = previewText.length > 0

  return (
    <Flex
      direction="col"
      className="rounded-lg border overflow-hidden bg-surface-sunken border-base"
    >
      {/* Header - always visible */}
      <Button
        kind="tertiary"
        size="small"
        onClick={() => canExpand && setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        aria-controls={`tool-content-${toolCall.id}`}
        className="w-full justify-start text-left p-0"
        disabled={!canExpand}
      >
        <Flex align="center" gap="2" className="w-full px-3 py-2">
          {/* Status Icon - spinner when running */}
          {isRunning ? (
            <LoadingSpinner size="small" className="h-4 w-4 shrink-0" aria-label={`${toolCall.name} is running`} />
          ) : (
            <span
              className="shrink-0"
              style={{ color: textColor }}
              aria-hidden="true"
            >
              {isComplete ? (
                <Check className="h-4 w-4" />
              ) : isError ? (
                <Close className="h-4 w-4" />
              ) : (
                <Clock className="h-4 w-4" />
              )}
            </span>
          )}

          {/* Tool Info */}
          <Flex direction="col" gap="0" className="flex-1 min-w-0">
            <Text kind="label/semibold/sm" style={{ color: textColor }}>
              {toolCall.name}
            </Text>
            {toolCall.workflow && (
              <Text kind="body/regular/xs" className="text-subtle truncate">
                via {toolCall.workflow}
              </Text>
            )}
          </Flex>

          {/* Timestamp */}
          {toolCall.timestamp && (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              {formatTime(toolCall.timestamp)}
            </Text>
          )}

          {/* Expand/collapse icon - hidden when running */}
          {canExpand && (
            <span
              className={`
                text-subtle transition-transform duration-200
                ${isExpanded ? 'rotate-180' : ''}
              `}
              aria-hidden="true"
            >
              <ChevronDown className="h-4 w-4" />
            </span>
          )}
        </Flex>
      </Button>

      {/* Collapsed preview */}
      {!isExpanded && hasPreview && (
        <Flex className="px-3 pb-2 border-t border-base">
          <Text kind="body/regular/sm" className="text-subtle truncate mt-1 font-mono">
            {previewText}
          </Text>
        </Flex>
      )}

      {/* Expanded content */}
      {isExpanded && (
        <Flex
          id={`tool-content-${toolCall.id}`}
          direction="col"
          gap="3"
          className="px-3 pb-3 border-t border-base"
        >
          {/* Arguments */}
          {toolCall.arguments && (
            <Flex direction="col" gap="1" className="mt-2">
              <Text kind="label/semibold/xs" className="text-subtle uppercase">
                Arguments
              </Text>
              <pre className="text-xs font-mono bg-surface-raised text-primary p-2 rounded overflow-x-auto">
                {formatArguments(toolCall.arguments, true)}
              </pre>
            </Flex>
          )}

          {/* Result */}
          {toolCall.result && (
            <Flex direction="col" gap="1">
              <Text kind="label/semibold/xs" className="text-subtle uppercase">
                Result
              </Text>
              <pre className="text-xs font-mono bg-surface-raised text-primary p-2 rounded overflow-x-auto whitespace-pre-wrap max-h-48">
                {toolCall.result}
              </pre>
            </Flex>
          )}

          {/* Error */}
          {toolCall.error && (
            <Flex direction="col" gap="1">
              <Text kind="label/semibold/xs" className="text-error uppercase">
                Error
              </Text>
              <Text kind="body/regular/sm" className="text-error">
                {toolCall.error}
              </Text>
            </Flex>
          )}
        </Flex>
      )}
    </Flex>
  )
}
