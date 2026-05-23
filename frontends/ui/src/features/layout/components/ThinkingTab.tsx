// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ThinkingTab Component
 *
 * Tab within ResearchPanel showing real-time thinking process during DEEP RESEARCH.
 * Uses dedicated state arrays for each category (LLM steps, agents, tool calls, files).
 *
 * Contains sub-tabs for different aspects of the thinking process:
 * - ThoughtTracesTab: LLM thought traces and chain-of-thought
 * - AgentsTab: Active agents with their tool calls shown as checklists
 * - ToolCallsTab: Tool calls made during processing
 * - FilesTab: Files created/modified during research
 * - Citation views: Sources read during research and referenced in the report
 *
 * SSE Events (Deep Research only):
 * - llm.start, llm.chunk, llm.end → deepResearchLLMSteps → ThoughtTracesTab
 * - workflow.start, workflow.end → deepResearchAgents → AgentsTab
 * - tool.start, tool.end → deepResearchToolCalls → AgentsTab (grouped by agent), ToolCallsTab
 * - artifact.update (file) → deepResearchFiles → FilesTab
 * - artifact.update (citation_source/citation_use) → deepResearchCitations → CitationCard
 */

'use client'

import { type FC, useState, useCallback, useMemo } from 'react'
import { Flex, SegmentedControl, Text } from '@/adapters/ui'
import { Book } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { ThoughtTracesTab } from './ThoughtTracesTab'
import { AgentsTab } from './AgentsTab'
import { ToolCallsTab } from './ToolCallsTab'
import { FilesTab } from './FilesTab'
import { CitationCard } from './CitationCard'
import { EMPTY_RESEARCH_DETAILS_HELP_TEXT } from './research-empty-state-copy'
import type { ThoughtInfo } from './ThoughtCard'
import type { ToolCallInfo } from './ToolCallCard'
import type {
  CitationSource,
  DeepResearchLLMStep,
  DeepResearchToolCall,
} from '@/features/chat/types'

/** Sub-tab types within ThinkingTab */
type ThinkingSubTab = 'thoughts' | 'agents' | 'tools' | 'files' | 'read' | 'referenced'
type CitationFilter = Extract<ThinkingSubTab, 'read' | 'referenced'>

/**
 * Map DeepResearchLLMStep to ThoughtInfo for ThoughtTracesTab
 */
const mapLLMStepToThoughtInfo = (step: DeepResearchLLMStep): ThoughtInfo => ({
  id: step.id,
  modelName: step.name,
  content: step.content,
  thinking: step.thinking,
  workflow: step.workflow,
  isStreaming: !step.isComplete,
  timestamp: step.timestamp,
  usage: step.usage
    ? {
        prompt_tokens: step.usage.input_tokens,
        completion_tokens: step.usage.output_tokens,
      }
    : undefined,
})

/**
 * Map DeepResearchToolCall to ToolCallInfo for ToolCallsTab
 */
const mapToolCallToToolCallInfo = (toolCall: DeepResearchToolCall): ToolCallInfo => ({
  id: toolCall.id,
  name: toolCall.name,
  arguments: toolCall.input,
  result: toolCall.output,
  status:
    toolCall.status === 'running'
      ? 'running'
      : toolCall.status === 'complete'
        ? 'complete'
        : 'error',
  timestamp: toolCall.timestamp,
  workflow: toolCall.workflow,
})

interface CitationListViewProps {
  filter: CitationFilter
  citations: CitationSource[]
}

/**
 * Citation view shown inside Thinking so source provenance stays grouped with
 * the rest of the replayed stream details instead of living in a separate tab.
 */
const CitationListView: FC<CitationListViewProps> = ({ filter, citations }) => {
  const filteredCitations = useMemo(() => {
    const matchingCitations =
      filter === 'referenced'
        ? citations.filter((citation) => citation.isCited)
        : citations.filter((citation) => !citation.isCited)

    return matchingCitations.sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )
  }, [citations, filter])

  const isEmpty = filteredCitations.length === 0
  const headerText = filter === 'referenced' ? 'Referenced' : 'Sources Read'
  const subheadingText =
    filter === 'referenced'
      ? 'Sources referenced in the final report.'
      : 'Sources discovered during research that were not referenced in the final report.'

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
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

      {isEmpty ? (
        <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
          <Book className="text-subtle mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-subtle">
            {filter === 'referenced'
              ? 'No referenced sources available.'
              : 'No read sources available.'}
          </Text>
          <Text kind="body/regular/sm" className="text-subtle mt-2">
            {EMPTY_RESEARCH_DETAILS_HELP_TEXT}
          </Text>
        </Flex>
      ) : (
        <Flex direction="col" gap="2" className="min-h-0 flex-1 overflow-y-auto">
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

/**
 * Thinking tab content with sub-tabs for thought traces, agents, files, and source provenance.
 * Consumes dedicated state arrays from the chat store.
 */
export const ThinkingTab: FC = () => {
  const deepResearchLLMSteps = useChatStore((state) => state.deepResearchLLMSteps)
  const deepResearchToolCalls = useChatStore((state) => state.deepResearchToolCalls)
  const deepResearchCitations = useChatStore((state) => state.deepResearchCitations)

  const [activeSubTab, setActiveSubTab] = useState<ThinkingSubTab>('agents')

  const handleSubTabChange = useCallback((value: string) => {
    setActiveSubTab(value as ThinkingSubTab)
  }, [])

  const thoughtTraces = useMemo(() => {
    return deepResearchLLMSteps.map(mapLLMStepToThoughtInfo).filter((thought) => {
      if (thought.isStreaming) return true
      const hasContent = thought.content && thought.content.trim().length > 0
      const hasThinking = thought.thinking && thought.thinking.trim().length > 0
      return hasContent || hasThinking
    })
  }, [deepResearchLLMSteps])

  const toolCalls = useMemo(() => {
    return deepResearchToolCalls.map(mapToolCallToToolCallInfo)
  }, [deepResearchToolCalls])

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      {/* Header with sub-tab selector */}
      <div className="shrink-0">
        <SegmentedControl
          value={activeSubTab}
          onValueChange={handleSubTabChange}
          size="small"
          items={[
            { value: 'thoughts', children: 'Thoughts' },
            { value: 'agents', children: 'Agents' },
            { value: 'tools', children: 'Tools' },
            { value: 'files', children: 'Files' },
            { value: 'read', children: 'Read' },
            { value: 'referenced', children: 'Referenced' },
          ]}
        />
      </div>

      {/* Sub-tab content */}
      <div className="min-h-0 flex-1">
        {activeSubTab === 'thoughts' && <ThoughtTracesTab thoughtTraces={thoughtTraces} />}
        {activeSubTab === 'agents' && <AgentsTab />}
        {activeSubTab === 'tools' && <ToolCallsTab toolCalls={toolCalls} />}
        {activeSubTab === 'files' && <FilesTab />}
        {activeSubTab === 'read' && (
          <CitationListView filter="read" citations={deepResearchCitations} />
        )}
        {activeSubTab === 'referenced' && (
          <CitationListView filter="referenced" citations={deepResearchCitations} />
        )}
      </div>
    </Flex>
  )
}
