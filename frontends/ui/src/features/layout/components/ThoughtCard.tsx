// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ThoughtCard Component
 *
 * Card displaying LLM inference activity including model name, streaming content,
 * and thinking/reasoning output (thought traces).
 *
 * SSE Events:
 * - llm.start: Creates card, shows model name and "thinking..." state
 * - llm.chunk: Appends streaming token to content (real-time display)
 * - llm.end: Completes card with final output and thinking metadata
 */

'use client'

import { type FC, useState } from 'react'
import { Flex, Text, Button } from '@/adapters/ui'
import { Chat, ChevronDown, LoadingSpinner } from '@/adapters/ui/icons'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'

/** Thought trace information from SSE events */
export interface ThoughtInfo {
  /** Unique identifier for this thought trace */
  id: string
  /** LLM model name */
  modelName: string
  /** Streaming or final output content */
  content: string
  /** Chain-of-thought reasoning (from metadata.thinking) */
  thinking?: string
  /** Parent agent */
  workflow?: string
  /** Whether currently receiving chunks */
  isStreaming: boolean
  /** When inference started */
  timestamp?: Date | string
  /** Token usage info (from llm.end) */
  usage?: {
    prompt_tokens?: number
    completion_tokens?: number
  }
}

interface ThoughtCardProps {
  /** Thought trace information */
  thought: ThoughtInfo
}

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Get preview text for collapsed state (prioritize thinking content)
 */
const getPreviewText = (thought: ThoughtInfo): string => {
  const source = thought.thinking || thought.content || ''
  const trimmed = source.substring(0, 130)
  return source.length > 130 ? `${trimmed}...` : trimmed
}

/**
 * Card showing LLM thought traces and output.
 */
export const ThoughtCard: FC<ThoughtCardProps> = ({ thought }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const previewText = getPreviewText(thought)
  const hasPreview = previewText.length > 0

  // Disable expansion while streaming (no content to show yet)
  const canExpand = !thought.isStreaming

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
        aria-controls={`thought-content-${thought.id}`}
        className="w-full justify-start text-left p-0"
        disabled={!canExpand}
      >
        <Flex align="center" gap="2" className="w-full px-3 py-2">
          {/* Status Icon - spinner when streaming */}
          {thought.isStreaming ? (
            <LoadingSpinner size="small" className="h-4 w-4 shrink-0" aria-label="Generating" />
          ) : (
            <span
              className="shrink-0"
              style={{ color: 'var(--text-color-subtle)' }}
              aria-hidden="true"
            >
              <Chat className="h-4 w-4" />
            </span>
          )}

          {/* Model Info */}
          <Flex align="center" gap="1" className="flex-1 min-w-0">
            <Text
              kind="label/semibold/sm"
              style={{
                color: thought.isStreaming
                  ? 'var(--text-color-feedback-info)'
                  : 'var(--text-color-subtle)',
              }}
            >
              {thought.modelName}
            </Text>
            {thought.workflow && (
              <Text kind="label/regular/sm" className="text-subtle truncate">
                via {thought.workflow}
              </Text>
            )}
          </Flex>

          {/* Token usage (when not streaming) */}
          {!thought.isStreaming && thought.usage && (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              Tokens: {thought.usage.prompt_tokens} in / {thought.usage.completion_tokens} out
            </Text>
          )}

          {/* Timestamp - only shown when not streaming */}
          {!thought.isStreaming && thought.timestamp && (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              {formatTime(thought.timestamp)}
            </Text>
          )}

          {/* Expand/collapse icon - hidden when streaming */}
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

      {/* Collapsed preview - show thinking content preview */}
      {!isExpanded && hasPreview && (
        <Flex className="px-3 pb-2 border-t border-base">
          <Text kind="body/regular/sm" className="text-subtle truncate mt-1">
            {previewText}
          </Text>
        </Flex>
      )}

      {/* Expanded content - show thinking and output together */}
      {isExpanded && (
        <Flex
          id={`thought-content-${thought.id}`}
          direction="col"
          gap="3"
          className="px-3 pb-3 border-t border-base"
        >
          {/* Thinking content (if available) */}
          {thought.thinking && (
            <div className="bg-surface-raised text-primary p-2 rounded text-sm italic mt-2">
              <MarkdownRenderer content={thought.thinking} compact />
            </div>
          )}

          {/* Output content */}
          {thought.content && (
            <Flex direction="col" gap="1" className={thought.thinking ? '' : 'mt-2'}>
              <Text kind="label/semibold/xs" className="text-subtle uppercase">
                Output
              </Text>
              <MarkdownRenderer content={thought.content} compact />
            </Flex>
          )}
        </Flex>
      )}
    </Flex>
  )
}
