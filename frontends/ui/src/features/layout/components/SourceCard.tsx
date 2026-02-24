// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SourceCard Component
 *
 * Card displaying a single source URL with optional metadata (title, snippet, discovery time).
 * Used in CitationsTab to show cited and referenced sources.
 *
 * SSE Events:
 * - artifact.update where data.type === 'citation_source': Discovered URL
 * - artifact.update where data.type === 'citation_use': Cited URL
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'

/** Source information from SSE events */
export interface SourceInfo {
  /** Unique identifier */
  id: string
  /** Source URL */
  url: string
  /** Page title if available */
  title?: string
  /** Content snippet if available */
  snippet?: string
  /** When source was found */
  discoveredAt?: Date | string
  /** Whether source is used in final report */
  isCited: boolean
}

interface SourceCardProps {
  /** Source information */
  source: SourceInfo
}

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Extract domain from URL for display
 */
const getDomain = (url: string): string => {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname.replace('www.', '')
  } catch {
    return url
  }
}

/**
 * Card showing a source URL with metadata.
 */
export const SourceCard: FC<SourceCardProps> = ({ source }) => {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block"
    >
      <Flex
        direction="col"
        gap="1"
        className={`
          p-3 rounded-lg border border-base
          hover:bg-surface-raised-50 transition-colors
          ${source.isCited ? 'border-l-2 border-l-success' : ''}
        `}
      >
        {/* Header row */}
        <Flex align="center" gap="2">
          {/* Cited indicator */}
          {source.isCited && (
            <span className="text-sm" aria-hidden="true">
              ✅
            </span>
          )}

          {/* Title or domain */}
          <Text kind="label/semibold/sm" className="flex-1 truncate">
            {source.title || getDomain(source.url)}
          </Text>

          {/* Timestamp */}
          {source.discoveredAt && (
            <Text kind="body/regular/xs" className="text-subtle shrink-0">
              {formatTime(source.discoveredAt)}
            </Text>
          )}
        </Flex>

        {/* URL */}
        <Text kind="body/regular/xs" className="text-subtle truncate">
          {source.url}
        </Text>

        {/* Snippet */}
        {source.snippet && (
          <Text kind="body/regular/xs" className="text-subtle line-clamp-2 mt-1">
            {source.snippet}
          </Text>
        )}
      </Flex>
    </a>
  )
}
