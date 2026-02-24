// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FilesTab Component
 *
 * Sub-tab within ThinkingTab displaying files created/modified during deep research.
 * Shows file artifacts like drafts, reports, and other generated content.
 *
 * SSE Events: artifact.update with type: "file"
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { Document } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat/store'
import { FileCard } from './FileCard'

/**
 * Files sub-tab content showing file artifacts from deep research.
 * Consumes deepResearchFiles from the chat store.
 */
export const FilesTab: FC = () => {
  // Get files from the dedicated store array
  const files = useChatStore((state) => state.deepResearchFiles)
  const isEmpty = files.length === 0

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {/* Header */}
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-subtle">
            Files
          </Text>
          {files.length > 0 && (
            <Text kind="body/regular/xs" className="text-subtle">
              {files.length}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/xs" className="text-subtle">
          Generated drafts, reports, and other file artifacts.
        </Text>
      </Flex>

      {/* Content */}
      {isEmpty ? (
        <Flex
          direction="col"
          align="center"
          justify="center"
          className="flex-1 text-center py-8"
        >
          <Document className="text-subtle mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-subtle">
            Generated files will appear here during research.
          </Text>
          <Text kind="body/regular/sm" className="text-subtle mt-2">
            Shows drafts, reports, and other file artifacts.
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="2" className="flex-1 min-h-0 overflow-y-auto">
          {files.map((file) => (
            <div key={file.id} className="shrink-0">
              <FileCard file={file} />
            </div>
          ))}
        </Flex>
      )}
    </Flex>
  )
}
