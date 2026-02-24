// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentPrompt Component
 *
 * Displays prompts from the agent that require user response.
 * This is a display-only component - user responds via the main chat input.
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { formatTime } from '@/shared/utils/format-time'
import { Chat } from '@/adapters/ui/icons'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import type { PromptType } from '../types'

export type { PromptType }

// Note: type is kept in props interface for API compatibility but not currently used

export interface AgentPromptProps {
  /** Unique identifier for this prompt */
  id: string
  /** Type of prompt */
  type: PromptType
  /** Main content/question from the agent */
  content: string
  /** Options for choice prompts (displayed as list) */
  options?: string[]
  /** Placeholder text for text input prompts (not used - display only) */
  placeholder?: string
  /** Whether the prompt has been responded to */
  isResponded?: boolean
  /** The user's response (if already responded) */
  response?: string
  /** Callback when user responds (not used - display only) */
  onRespond?: (promptId: string, response: string) => void
  /** Timestamp (Date or ISO string from persisted state) */
  timestamp?: Date | string
}

/**
 * Agent prompt component - display only.
 * User responds via the main chat input area.
 */
export const AgentPrompt: FC<AgentPromptProps> = ({
  type: _type,
  content,
  options = [],
  isResponded = false,
  response,
  timestamp,
}) => {
  return (
    <Flex justify="start" className="w-full">
      <Flex direction="col" className="max-w-[85%]">
        <Flex
          direction="col"
          gap="3"
          className="bg-surface-sunken-opaque border-base rounded-br-xl rounded-tl-xl rounded-tr-xl border p-4 break-words overflow-hidden"
        >
          {/* Agent icon and label */}
          <Flex align="center" gap="2" className={isResponded ? 'opacity-75' : ''}>
            <Chat className="text-secondary h-5 w-5" />
            <Text kind="label/semibold/sm" className="text-secondary">
              {isResponded ? 'Agent received your input' : 'Agent needs your input'}
            </Text>
          </Flex>

          {/* Content - rendered as markdown */}
          <div className={`prose prose-sm max-w-none ${isResponded ? 'opacity-75' : ''}`}>
            <MarkdownRenderer content={content} />
          </div>

          {/* Options list for choice prompts */}
          {options.length > 0 && !isResponded && <OptionsList options={options} />}

          {/* Response display (only shown after user responds) */}
          {isResponded && <ResponseDisplay response={response} />}
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

/**
 * Display options for choice prompts (read-only)
 */
const OptionsList: FC<{ options: string[] }> = ({ options }) => {
  return (
    <Flex direction="col" gap="1">
      {options.map((option, index) => (
        <Flex
          key={index}
          align="center"
          gap="2"
          className="bg-surface-raised border-base rounded-lg border p-2"
        >
          <span className="text-subtle text-xs">{index + 1}.</span>
          <Text kind="body/regular/sm">{option}</Text>
        </Flex>
      ))}
    </Flex>
  )
}

/**
 * Display the user's response after submission
 */
const ResponseDisplay: FC<{ response?: string }> = ({ response }) => {
  if (!response) return null

  return (
    <Flex align="center" gap="2" className="bg-surface-raised border-base rounded-lg border p-2">
      <Chat className="text-subtle h-4 w-4" />
      <Text kind="body/regular/sm" className="text-subtle">
        Your response: <span className="text-primary">{response}</span>
      </Text>
    </Flex>
  )
}

