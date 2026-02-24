// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * CitationsTab Component
 *
 * Displays referenced sources and citations from the agent's research.
 * Shows both "Referenced" (citation_source) and "Cited" (citation_use) sources.
 *
 * SSE Events:
 * - artifact.update type: "citation_source" - Sources discovered during search
 * - artifact.update type: "citation_use" - Sources actually cited in the report
 */

'use client'

import { type FC, useMemo, useState, useCallback } from 'react'
import { Flex, Text, SegmentedControl } from '@/adapters/ui'
import { Book } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { CitationCard } from './CitationCard'

/** Filter options for citation display */
type CitationFilter = 'referenced' | 'read'

/**
 * Citations tab content - displays sources and references.
 * Separates citations into "Cited" (used in report) and "Referenced" (discovered).
 */
export const CitationsTab: FC = () => {
  const { deepResearchCitations } = useChatStore()
  const [filter, setFilter] = useState<CitationFilter>('referenced')

  const handleFilterChange = useCallback((value: string) => {
    setFilter(value as CitationFilter)
  }, [])

  // Filter and sort citations
  const filteredCitations = useMemo(() => {
    const citations =
      filter === 'referenced'
        ? deepResearchCitations.filter((c) => c.isCited)
        : deepResearchCitations.filter((c) => !c.isCited)

    // Sort by timestamp, newest first
    return citations.sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )
  }, [deepResearchCitations, filter])

  const isEmpty = filteredCitations.length === 0

  // Get header and subheading text based on current filter
  const headerText = filter === 'referenced' ? 'Referenced' : 'Sources Read'
  const subheadingText =
    filter === 'referenced'
      ? 'Sources referenced in the final report.'
      : 'Sources discovered during research that were not referenced in the final report.'

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {/* Filter control */}
      <div className="shrink-0">
        <SegmentedControl
          value={filter}
          onValueChange={handleFilterChange}
          size="small"
          items={[
            { value: 'referenced', children: 'Referenced' },
            { value: 'read', children: 'Read' },
          ]}
        />
      </div>

      {/* Tab header with subheading */}
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-subtle">
            {headerText}
          </Text>
          {filteredCitations.length > 0 && (
            <Text kind="body/regular/xs" className="text-subtle">
              {filteredCitations.length}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/xs" className="text-subtle">
          {subheadingText}
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
          <Book className="text-subtle mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-subtle">
            {filter === 'referenced'
              ? 'No referenced sources yet. Sources used for the report will appear here.'
              : 'No sources read yet. Sources discovered during research will appear here.'}
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="2" className="flex-1 min-h-0 overflow-y-auto">
          {filteredCitations.map((citation) => (
            <div key={citation.id} className="shrink-0">
              <CitationCard citation={citation} />
            </div>
          ))}
        </Flex>
      )}
    </Flex>
  )
}
