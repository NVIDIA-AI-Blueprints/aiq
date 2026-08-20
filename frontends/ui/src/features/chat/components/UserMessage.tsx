// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * UserMessage Component
 *
 * User message bubble displayed in the chat area.
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import { formatTime } from '@/shared/utils/format-time'

export interface UserMessageProps {
  content: string
  /** Timestamp rendered below the bubble, right-aligned. */
  timestamp?: Date | string
}

/**
 * User message bubble component
 */
export const UserMessage: FC<UserMessageProps> = ({ content, timestamp }) => {
  return (
    <Flex justify="end" className="w-full">
      <Flex direction="col" align="end" className="max-w-[74%]">
        <div className="user-message-bubble break-words rounded-[var(--radius-card)] rounded-br-[2px] border px-4 py-3">
          <MarkdownRenderer content={content} />
        </div>
        {timestamp && (
          <Text kind="body/regular/xs" className="mono-meta text-subtle mr-1 mt-1">
            {formatTime(timestamp)}
          </Text>
        )}
      </Flex>
    </Flex>
  )
}
