// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FileCard Component
 *
 * Expandable card displaying a file artifact from deep research.
 * Shows filename header with expandable content view.
 *
 * SSE Events:
 * - artifact.update (type: "file"): Creates card with filename and content
 */

'use client'

import { type FC, useState } from 'react'
import { Flex, Text, Button } from '@/adapters/ui'
import { Document, ChevronDown } from '@/adapters/ui/icons'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'

/** File artifact information from SSE events */
export interface FileInfo {
  /** Unique identifier for this file */
  id: string
  /** File name/path */
  filename: string
  /** File content */
  content: string
  /** When file was created/updated */
  timestamp?: Date | string
}

interface FileCardProps {
  /** File artifact information */
  file: FileInfo
}

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Get file extension for display styling
 */
const getFileExtension = (filename: string): string => {
  const parts = filename.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
}

/**
 * Check if file content should be rendered as markdown
 */
const isMarkdownFile = (filename: string): boolean => {
  const ext = getFileExtension(filename)
  return ['md', 'markdown'].includes(ext)
}

/**
 * Expandable card showing a file artifact's details.
 */
export const FileCard: FC<FileCardProps> = ({ file }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  // Content preview (first 100 chars)
  const contentPreview = file.content
    ? file.content.substring(0, 100).replace(/\n/g, ' ') + (file.content.length > 100 ? '...' : '')
    : ''

  const shouldRenderMarkdown = isMarkdownFile(file.filename)

  return (
    <Flex
      direction="col"
      className="rounded-lg border overflow-hidden bg-surface-sunken border-base"
    >
      {/* Header - always visible */}
      <Button
        kind="tertiary"
        size="small"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        aria-controls={`file-content-${file.id}`}
        className="w-full justify-start text-left p-0"
      >
        <Flex align="center" gap="2" className="w-full px-3 py-2">
          {/* File Icon */}
          <span
            className="shrink-0"
            style={{ color: 'var(--text-color-subtle)' }}
            aria-hidden="true"
          >
            <Document className="h-4 w-4" />
          </span>

          {/* File Info */}
          <Flex direction="col" gap="0" className="flex-1 min-w-0">
            <Text kind="label/semibold/sm" className="text-default truncate">
              {file.filename}
            </Text>
          </Flex>

          {/* Line count */}
          {file.content && (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              {file.content.split('\n').length} lines
            </Text>
          )}

          {/* Timestamp */}
          {file.timestamp && (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              {formatTime(file.timestamp)}
            </Text>
          )}

          {/* Expand/collapse icon */}
          <span
            className={`
              text-subtle transition-transform duration-200
              ${isExpanded ? 'rotate-180' : ''}
            `}
            aria-hidden="true"
          >
            <ChevronDown className="h-4 w-4" />
          </span>
        </Flex>
      </Button>

      {/* Collapsed preview */}
      {!isExpanded && contentPreview && (
        <Flex className="px-3 pb-2 border-t border-base">
          <Text kind="body/regular/sm" className="text-subtle truncate mt-1 font-mono">
            {contentPreview}
          </Text>
        </Flex>
      )}

      {/* Expanded content */}
      {isExpanded && (
        <Flex
          id={`file-content-${file.id}`}
          direction="col"
          gap="3"
          className="px-3 pb-3 border-t border-base"
        >
          {/* File Content */}
          {file.content && (
            <Flex direction="col" gap="1" className="mt-2">
              <Text kind="label/semibold/xs" className="text-subtle uppercase">
                Content
              </Text>
              {shouldRenderMarkdown ? (
                <div className="bg-surface-raised text-primary p-2 rounded overflow-auto max-h-96">
                  <MarkdownRenderer content={file.content} compact />
                </div>
              ) : (
                <pre className="text-xs font-mono bg-surface-raised text-primary p-2 rounded overflow-auto whitespace-pre-wrap max-h-96">
                  {file.content}
                </pre>
              )}
            </Flex>
          )}
        </Flex>
      )}
    </Flex>
  )
}
