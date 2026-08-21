// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentsTab Component (the "Steps" view)
 *
 * The single authoritative view of what the agent did. It renders the SAME
 * phased trace as the inline chat thinking surface (ChatThinking): tool labels,
 * input descriptions, durations, generated queries, web searches, and
 * explanations, by adapting the deep-research run (agents + tool calls) into the
 * step stream ChatThinking consumes. This keeps the report's "thinking" tab
 * consistent with what the user saw live in chat.
 *
 * SSE Events: workflow.start, workflow.end, tool.start, tool.end
 */

'use client'

import { type FC, useEffect, useMemo, useRef } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { useShallow } from 'zustand/react/shallow'
import { Wand } from '@/adapters/ui/icons'
import { useChatStore } from '@/features/chat'
import { ChatThinking } from '@/features/chat/components/ChatThinking'
import { deepResearchToThinkingSteps } from '@/features/chat/lib/deep-research-trace'
import { isPinnedToBottom } from '@/shared/lib/scroll'
import { EMPTY_RESEARCH_DETAILS_HELP_TEXT } from './research-empty-state-copy'

/**
 * Steps view: the deep-research run rendered as the inline chat trace. Agents are
 * phase heads; their tool calls (with queries and input summaries) and
 * explanations fold underneath, identical to the live chat thinking surface.
 */
export const AgentsTab: FC = () => {
  const { deepResearchAgents, deepResearchToolCalls } = useChatStore(
    useShallow((s) => ({
      deepResearchAgents: s.deepResearchAgents,
      deepResearchToolCalls: s.deepResearchToolCalls,
    }))
  )

  const steps = useMemo(
    () => deepResearchToThinkingSteps(deepResearchAgents, deepResearchToolCalls),
    [deepResearchAgents, deepResearchToolCalls]
  )

  const isEmpty = deepResearchAgents.length === 0 && deepResearchToolCalls.length === 0
  const runningCount = useMemo(
    () => steps.filter((s) => s.isTopLevel && s.status === 'running').length,
    [steps]
  )
  const renderedGroupCount = useMemo(() => steps.filter((s) => s.isTopLevel).length, [steps])

  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scrollRef.current
    if (!el || runningCount === 0) return
    if (isPinnedToBottom(el.scrollTop, el.scrollHeight, el.clientHeight)) {
      el.scrollTop = el.scrollHeight
    }
  }, [steps, runningCount])

  return (
    <Flex direction="col" gap="4" className="h-full min-h-0">
      <Flex direction="col" gap="1" className="shrink-0">
        <Flex align="center" gap="2">
          <Text kind="label/semibold/md" className="text-primary">
            Steps
          </Text>
          {!isEmpty && (
            <Text kind="body/regular/xs" className="text-secondary">
              {runningCount > 0 ? `${runningCount} running` : `${renderedGroupCount}`}
            </Text>
          )}
        </Flex>
        <Text kind="body/regular/sm" className="text-secondary">
          What the agent did, grouped by step.
        </Text>
      </Flex>

      {isEmpty ? (
        <Flex direction="col" align="center" justify="center" className="flex-1 py-8 text-center">
          <Wand className="text-secondary mb-3 h-8 w-8" />
          <Text kind="body/regular/md" className="text-secondary">
            Research steps will appear here as the agent works.
          </Text>
          <Text kind="body/regular/sm" className="text-secondary mt-2">
            {EMPTY_RESEARCH_DETAILS_HELP_TEXT}
          </Text>
        </Flex>
      ) : (
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <ChatThinking steps={steps} embedded isThinking={runningCount > 0} />
        </div>
      )}
    </Flex>
  )
}
