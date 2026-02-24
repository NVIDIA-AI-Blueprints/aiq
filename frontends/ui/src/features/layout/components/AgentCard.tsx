// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentCard Component
 *
 * Expandable card displaying a single agent/workflow with its name, status,
 * tool calls as a checklist, and output.
 *
 * SSE Events:
 * - workflow.start: Creates or updates card to "running" status
 * - workflow.end: Updates card to "complete" status
 * - tool.start/end: Tool calls linked via agent_id
 */

'use client'

import { type FC, useState } from 'react'
import { Flex, Text, Button, Checkbox } from '@/adapters/ui'
import { ChevronDown, Check, Close, Clock, Search, Document, Edit, Wand, LoadingSpinner } from '@/adapters/ui/icons'
import type { DeepResearchToolCall } from '@/features/chat/types'

/** Maximum characters for truncated query display */
const MAX_QUERY_LENGTH = 120

/** Tool names that are search/research tools */
const SEARCH_TOOL_PATTERNS = ['search', 'web', 'tavily', 'google', 'bing']

/** Tool names that are file operations */
const FILE_TOOL_PATTERNS = ['write_file', 'read_file', 'file']

/** Tool names that are todo/planning operations */
const PLANNING_TOOL_PATTERNS = ['write_todo', 'todo', 'plan']

/** Agent/workflow information from SSE events */
export interface AgentInfo {
  /** Unique identifier for this agent instance */
  id: string
  /** Agent/workflow name (e.g., "planner-agent", "researcher-agent") */
  name: string
  /** Current execution status */
  status: 'pending' | 'running' | 'complete' | 'error'
  /** Description of current activity */
  currentTask?: string
  /** When agent started */
  startedAt?: Date | string
  /** When agent completed */
  completedAt?: Date | string
  /** Output from the agent (after completion) */
  output?: string
  /** Tool calls made by this agent */
  toolCalls?: DeepResearchToolCall[]
}

interface AgentCardProps {
  /** Agent information */
  agent: AgentInfo
  /** Whether to start expanded */
  defaultExpanded?: boolean
}

/**
 * Determine the tool type category
 */
type ToolType = 'search' | 'file' | 'planning' | 'other'

const getToolType = (toolName: string): ToolType => {
  const lowerName = toolName.toLowerCase()
  if (SEARCH_TOOL_PATTERNS.some((p) => lowerName.includes(p))) return 'search'
  if (FILE_TOOL_PATTERNS.some((p) => lowerName.includes(p))) return 'file'
  if (PLANNING_TOOL_PATTERNS.some((p) => lowerName.includes(p))) return 'planning'
  return 'other'
}

/**
 * Get icon component for tool type
 */
const getToolIcon = (toolType: ToolType) => {
  switch (toolType) {
    case 'search':
      return Search
    case 'file':
      return Document
    case 'planning':
      return Edit
    default:
      return Wand
  }
}

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Get the query/description from tool call input, with truncation
 */
const getToolCallDescription = (toolCall: DeepResearchToolCall, truncate = true): string => {
  if (!toolCall.input) return toolCall.name

  const input = toolCall.input as Record<string, unknown>
  const rawDescription = (input.question || input.query || input.search_query || input.filename || input.content || toolCall.name) as string

  if (!truncate || rawDescription.length <= MAX_QUERY_LENGTH) {
    return rawDescription
  }

  return rawDescription.substring(0, MAX_QUERY_LENGTH) + '...'
}

/**
 * Get display name for a tool (formatted)
 */
const getToolDisplayName = (toolName: string): string => {
  return toolName
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Deduplicate tool calls by query text, keeping the most recent status
 */
const dedupeToolCalls = (toolCalls: DeepResearchToolCall[]): DeepResearchToolCall[] => {
  const seen = new Map<string, DeepResearchToolCall>()
  
  for (const tc of toolCalls) {
    const key = getToolCallDescription(tc, false)
    const existing = seen.get(key)
    
    if (!existing) {
      seen.set(key, tc)
    } else if (tc.status === 'complete' && existing.status !== 'complete') {
      seen.set(key, tc)
    }
  }
  
  return Array.from(seen.values())
}

/**
 * Expandable card showing a single agent's status, tool calls, and output.
 */
export const AgentCard: FC<AgentCardProps> = ({ agent, defaultExpanded = true }) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  const isRunning = agent.status === 'running'
  const isComplete = agent.status === 'complete'
  const isError = agent.status === 'error'

  const rawToolCalls = agent.toolCalls || []
  const toolCalls = dedupeToolCalls(rawToolCalls)
  const completedToolCalls = toolCalls.filter((tc) => tc.status === 'complete')
  const searchToolCalls = toolCalls.filter((tc) => getToolType(tc.name) === 'search')
  const hasToolCalls = toolCalls.length > 0
  const hasExpandableContent = hasToolCalls || agent.currentTask || agent.output

  // Disable expansion while running (content is still being populated)
  const canExpand = hasExpandableContent && !isRunning

  const textColor = isRunning
    ? 'var(--text-color-feedback-info)'
    : isComplete
      ? 'var(--text-color-feedback-success)'
      : isError
        ? 'var(--text-color-feedback-danger)'
        : 'var(--text-color-subtle)'

  const toolCountLabel = searchToolCalls.length > 0
    ? `${searchToolCalls.filter((tc) => tc.status === 'complete').length}/${searchToolCalls.length} queries`
    : `${completedToolCalls.length}/${toolCalls.length} tools`

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
        aria-controls={`agent-content-${agent.id}`}
        className="w-full justify-start text-left p-0"
        disabled={!canExpand}
      >
        <Flex align="center" gap="2" className="w-full px-3 py-2">
          {/* Status Icon - spinner when running */}
          {isRunning ? (
            <LoadingSpinner size="small" className="h-4 w-4 shrink-0" aria-label={`${agent.name} is running`} />
          ) : (
            <span className="shrink-0" style={{ color: textColor }} aria-hidden="true">
              {isComplete ? (
                <Check className="h-4 w-4" />
              ) : isError ? (
                <Close className="h-4 w-4" />
              ) : (
                <Clock className="h-4 w-4" />
              )}
            </span>
          )}

          {/* Agent Info */}
          <Flex direction="col" gap="0" className="flex-1 min-w-0">
            <Flex align="center" gap="2">
              <Text kind="label/semibold/sm" style={{ color: textColor }}>
                {agent.name}
              </Text>
              {hasToolCalls && (
                <Text kind="body/regular/xs" className="text-subtle">
                  {toolCountLabel}
                </Text>
              )}
            </Flex>
          </Flex>

          {/* Timestamp */}
          {agent.completedAt ? (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              {formatTime(agent.completedAt)}
            </Text>
          ) : agent.startedAt ? (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              Started: {formatTime(agent.startedAt)}
            </Text>
          ) : null}

          {/* Expand/collapse icon - hidden when running */}
          {canExpand && (
            <span
              className={`text-subtle transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
              aria-hidden="true"
            >
              <ChevronDown className="h-4 w-4" />
            </span>
          )}
        </Flex>
      </Button>

      {/* Expanded content */}
      {isExpanded && hasExpandableContent && (
        <Flex
          id={`agent-content-${agent.id}`}
          direction="col"
          gap="2"
          className="px-3 pb-3 border-t border-base pt-2"
        >
          {/* Current task description - truncated */}
          {agent.currentTask && (
            <Text kind="body/regular/sm" className="text-subtle line-clamp-3">
              {agent.currentTask.length > 200
                ? agent.currentTask.substring(0, 200) + '...'
                : agent.currentTask}
            </Text>
          )}

          {/* Tool calls as checklist */}
          {hasToolCalls && (
            <Flex direction="col" gap="1">
              {toolCalls.map((toolCall) => {
                const isToolComplete = toolCall.status === 'complete'
                const isToolRunning = toolCall.status === 'running'
                const toolType = getToolType(toolCall.name)
                const ToolIcon = getToolIcon(toolType)
                const description = getToolCallDescription(toolCall)
                const isSearchType = toolType === 'search'

                return (
                  <Flex
                    key={toolCall.id}
                    align="start"
                    gap="2"
                    className={`py-1 ${isToolComplete ? 'opacity-70' : ''}`}
                  >
                    {isToolRunning ? (
                      <LoadingSpinner size="small" className="mt-0.5 shrink-0 h-4 w-4" aria-label="Running" />
                    ) : (
                      <Checkbox
                        checked={isToolComplete}
                        disabled
                        aria-label={description}
                        className="mt-0.5 shrink-0"
                      />
                    )}
                    <Flex direction="col" gap="0" className="flex-1 min-w-0">
                      <Flex align="start" gap="1">
                        <ToolIcon className="h-3 w-3 text-subtle shrink-0 mt-0.5" />
                        <Text
                          kind="body/regular/sm"
                          className={`${isToolComplete ? 'text-subtle' : ''} line-clamp-2`}
                        >
                          {isSearchType ? (
                            description
                          ) : (
                            <>
                              <span className="font-medium">{getToolDisplayName(toolCall.name)}</span>
                              {description !== toolCall.name && (
                                <span className="text-subtle">: {description}</span>
                              )}
                            </>
                          )}
                        </Text>
                      </Flex>
                    </Flex>
                  </Flex>
                )
              })}
            </Flex>
          )}
        </Flex>
      )}
    </Flex>
  )
}
