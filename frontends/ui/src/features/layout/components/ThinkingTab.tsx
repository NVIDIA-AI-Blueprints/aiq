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
 *
 * SSE Events (Deep Research only):
 * - llm.start, llm.chunk, llm.end → deepResearchLLMSteps → ThoughtTracesTab
 * - workflow.start, workflow.end → deepResearchAgents → AgentsTab
 * - tool.start, tool.end → deepResearchToolCalls → AgentsTab (grouped by agent), ToolCallsTab
 * - artifact.update (file) → deepResearchFiles → FilesTab
 */

'use client'

import { type FC, useState, useCallback, useMemo } from 'react'
import { Flex, SegmentedControl } from '@/adapters/ui'
import { useChatStore } from '@/features/chat'
import { ThoughtTracesTab } from './ThoughtTracesTab'
import { AgentsTab } from './AgentsTab'
import { ToolCallsTab } from './ToolCallsTab'
import { FilesTab } from './FilesTab'
import type { ThoughtInfo } from './ThoughtCard'
import type { ToolCallInfo } from './ToolCallCard'
import type { DeepResearchLLMStep, DeepResearchToolCall } from '@/features/chat/types'

/** Sub-tab types within ThinkingTab */
type ThinkingSubTab = 'thoughts' | 'agents' | 'tools' | 'files'

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
  status: toolCall.status === 'running' ? 'running' : toolCall.status === 'complete' ? 'complete' : 'error',
  timestamp: toolCall.timestamp,
  workflow: toolCall.workflow,
})

/**
 * Thinking tab content with sub-tabs for thought traces, agents, and files.
 * Consumes dedicated state arrays from the chat store.
 */
export const ThinkingTab: FC = () => {
  const deepResearchLLMSteps = useChatStore((state) => state.deepResearchLLMSteps)
  const deepResearchToolCalls = useChatStore((state) => state.deepResearchToolCalls)

  const [activeSubTab, setActiveSubTab] = useState<ThinkingSubTab>('agents')

  const handleSubTabChange = useCallback((value: string) => {
    setActiveSubTab(value as ThinkingSubTab)
  }, [])

  const thoughtTraces = useMemo(() => {
    return deepResearchLLMSteps
      .map(mapLLMStepToThoughtInfo)
      .filter((thought) => {
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
          ]}
        />
      </div>

      {/* Sub-tab content */}
      <div className="flex-1 min-h-0">
        {activeSubTab === 'thoughts' && <ThoughtTracesTab thoughtTraces={thoughtTraces} />}
        {activeSubTab === 'agents' && <AgentsTab />}
        {activeSubTab === 'tools' && <ToolCallsTab toolCalls={toolCalls} />}
        {activeSubTab === 'files' && <FilesTab />}
      </div>
    </Flex>
  )
}
