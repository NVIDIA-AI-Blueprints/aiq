// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ThinkingTab Component
 *
 * The "Thinking" tab of the research panel, reduced to two clear sub-tabs:
 *
 * - STEPS: the single authoritative view of what the agent did. Tool calls are
 *   grouped under their parent agent (human label + status + count). Raw model
 *   reasoning is demoted to a collapsed disclosure inside that view. A thin
 *   "Generated files" section appears only when files exist.
 * - SOURCES: one merged list of every source the agent touched, with a small
 *   All / Cited filter ("Cited in report" vs "Other sources found").
 *
 * SSE Events (Deep Research only):
 * - workflow.start/end, tool.start/end, llm.start/end → Steps
 * - artifact.update (file) → Steps (Generated files section)
 * - artifact.update (citation_source/citation_use) → Sources
 */

'use client'

import { type FC, useState, useCallback, useMemo } from 'react'
import { Flex, SegmentedControl, Text } from '@/adapters/ui'
import { Book, Document, ChevronDown } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { useShallow } from 'zustand/react/shallow'
import { AgentsTab } from './AgentsTab'
import { FileCard } from './FileCard'
import { CitationCard } from './CitationCard'
import { EMPTY_RESEARCH_DETAILS_HELP_TEXT } from './research-empty-state-copy'
import type { CitationSource } from '@/features/chat/types'

/** Top-level sub-tabs within Thinking. */
type ThinkingSubTab = 'steps' | 'sources'

/** Source-list filter: every source, or only those cited in the report. */
type SourceFilter = 'all' | 'cited'

interface SourcesViewProps {
  citations: CitationSource[]
}

/**
 * One merged source list (replaces the old "Read" + "Referenced" sub-tabs) with
 * an All / Cited filter. Cited sources are labelled "Cited in report" and the
 * rest "Other sources found".
 */
const SourcesView: FC<SourcesViewProps> = ({ citations }) => {
  const [filter, setFilter] = useState<SourceFilter>('all')

  const sorted = useMemo(
    () =>
      [...citations].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      ),
    [citations]
  )

  const cited = useMemo(() => sorted.filter((c) => c.isCited), [sorted])
  const other = useMemo(() => sorted.filter((c) => !c.isCited), [sorted])
  const shown = filter === 'cited' ? cited : sorted

  const handleFilterChange = useCallback((value: string) => {
    setFilter(value as SourceFilter)
  }, [])

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      <Flex direction="col" gap="2" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-primary">
            Sources
          </Text>
          {sorted.length > 0 && (
            <Text kind="body/regular/xs" className="text-secondary tabular-nums">
              {sorted.length}
            </Text>
          )}
        </Flex>
        {sorted.length > 0 && (
          <div>
            <SegmentedControl
              value={filter}
              onValueChange={handleFilterChange}
              size="small"
              items={[
                { value: 'all', children: 'All' },
                { value: 'cited', children: `Cited (${cited.length})` },
              ]}
            />
          </div>
        )}
      </Flex>

      {shown.length === 0 ? (
        filter === 'cited' && sorted.length > 0 ? (
          <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
            <Book className="text-secondary mb-3 h-8 w-8" />
            <Text kind="body/regular/md" className="text-secondary">
              No sources were cited in the report.
            </Text>
            <Text kind="body/regular/sm" className="text-secondary mt-2">
              Switch to All to see every source the agent found.
            </Text>
          </Flex>
        ) : (
          <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
            <Book className="text-secondary mb-3 h-8 w-8" />
            <Text kind="body/regular/md" className="text-secondary">
              Sources the agent reads will appear here.
            </Text>
            <Text kind="body/regular/sm" className="text-secondary mt-2">
              {EMPTY_RESEARCH_DETAILS_HELP_TEXT}
            </Text>
          </Flex>
        )
      ) : (
        <Flex direction="col" gap="3" className="min-h-0 flex-1 overflow-y-auto">
          {filter === 'all' ? (
            <>
              {cited.length > 0 && (
                <Flex direction="col" gap="2">
                  <Text kind="label/semibold/sm" className="text-secondary">
                    Cited in report
                  </Text>
                  {cited.map((citation) => (
                    <div key={citation.id} className="shrink-0">
                      <CitationCard citation={citation} />
                    </div>
                  ))}
                </Flex>
              )}
              {other.length > 0 && (
                <Flex direction="col" gap="2">
                  <Text kind="label/semibold/sm" className="text-secondary">
                    Other sources found
                  </Text>
                  {other.map((citation) => (
                    <div key={citation.id} className="shrink-0">
                      <CitationCard citation={citation} />
                    </div>
                  ))}
                </Flex>
              )}
            </>
          ) : (
            shown.map((citation) => (
              <div key={citation.id} className="shrink-0">
                <CitationCard citation={citation} />
              </div>
            ))
          )}
        </Flex>
      )}
    </Flex>
  )
}

/**
 * Thinking tab content, reduced to Steps + Sources. Consumes dedicated state
 * arrays from the chat store.
 */
export const ThinkingTab: FC = () => {
  const { deepResearchCitations, deepResearchFiles } = useChatStore(
    useShallow((s) => ({
      deepResearchCitations: s.deepResearchCitations,
      deepResearchFiles: s.deepResearchFiles,
    }))
  )

  const [activeSubTab, setActiveSubTab] = useState<ThinkingSubTab>('steps')
  const [showFiles, setShowFiles] = useState(false)

  const handleSubTabChange = useCallback((value: string) => {
    setActiveSubTab(value as ThinkingSubTab)
  }, [])

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {}
      <div className="shrink-0">
        <SegmentedControl
          value={activeSubTab}
          onValueChange={handleSubTabChange}
          size="small"
          items={[
            { value: 'steps', children: 'Steps' },
            { value: 'sources', children: 'Sources' },
          ]}
        />
      </div>

      {}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {activeSubTab === 'steps' && (
          <Flex direction="col" gap="3" className="h-full min-h-0">
            <div className="min-h-0 flex-1 overflow-y-auto">
              <AgentsTab />
            </div>

            {}
            {deepResearchFiles.length > 0 && (
              <Flex direction="col" gap="2" className="border-base shrink-0 border-t pt-3">
                <button
                  type="button"
                  onClick={() => setShowFiles((v) => !v)}
                  aria-expanded={showFiles}
                  className="text-secondary hover:text-primary flex items-center gap-1.5 self-start transition-colors"
                >
                  <Document className="h-4 w-4" aria-hidden="true" />
                  <Text kind="body/regular/sm">
                    Generated files ({deepResearchFiles.length})
                  </Text>
                  <ChevronDown
                    className={`h-4 w-4 transition-transform duration-200 ${showFiles ? 'rotate-180' : ''}`}
                    aria-hidden="true"
                  />
                </button>
                {showFiles && (
                  <Flex direction="col" gap="2" className="max-h-64 overflow-y-auto">
                    {deepResearchFiles.map((file) => (
                      <div key={file.id} className="shrink-0">
                        <FileCard file={file} />
                      </div>
                    ))}
                  </Flex>
                )}
              </Flex>
            )}
          </Flex>
        )}

        {activeSubTab === 'sources' && (
          <div className="min-h-0 flex-1 overflow-hidden">
            <SourcesView citations={deepResearchCitations} />
          </div>
        )}
      </div>
    </Flex>
  )
}
