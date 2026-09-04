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
  /** Timestamp of the message (Date or ISO string from persisted state) */
  timestamp?: Date | string
}

/**
 * User message bubble component
 */
export const UserMessage: FC<UserMessageProps> = ({ content, timestamp }) => {
  return (
    <Flex justify="end" className="w-full">
      <Flex direction="col" align="end" className="max-w-[80%]">
        <Flex className="bg-surface-sunken-opaque border border-base rounded-bl-xl rounded-tl-xl rounded-tr-xl p-4">
          <MarkdownRenderer content={content} />
        </Flex>
        {timestamp && (
          <Text kind="body/regular/xs" className="text-subtle mt-1 ml-3 self-start">
            {formatTime(timestamp)}
          </Text>
        )}
      </Flex>
    </Flex>
  )
}
