// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Message Pruning for Storage
 *
 * Utilities for removing heavy, refetchable data from messages before
 * saving to localStorage. Research data can be fetched from backend on demand.
 */

import type { ChatMessage } from '../types'

/**
 * Cap string content to prevent excessively large values.
 */
export const capString = (value: string, max: number): string => {
  return value.length > max ? value.slice(0, max) : value
}

/**
 * Strip thinking steps for storage. ChatThinking only renders displayName
 * and timestamp — content/rawPayload/category are never displayed.
 *
 * - Deep research steps (isDeepResearch=true) are removed entirely since
 *   they are refetched from the async backend API.
 * - Shallow steps keep only the fields needed for ChatThinking display.
 */
export const stripThinkingStepsForStorage = (
  steps: NonNullable<ChatMessage['thinkingSteps']>
): NonNullable<ChatMessage['thinkingSteps']> => {
  return steps
    .filter((step) => !step.isDeepResearch)
    .map((step) => ({
      id: step.id,
      userMessageId: step.userMessageId,
      functionName: step.functionName,
      displayName: step.displayName,
      content: '',
      timestamp: step.timestamp,
      isComplete: step.isComplete,
      isDeepResearch: step.isDeepResearch,
      isTopLevel: step.isTopLevel,
      category: step.category,
    }))
}

/**
 * Prune plan messages to reduce storage size.
 * Keeps plan structure but caps text content.
 * planMessages cannot be refetched (WebSocket only).
 */
export const prunePlanMessages = (
  planMessages: NonNullable<ChatMessage['planMessages']>,
  maxTextLength = 10000
): NonNullable<ChatMessage['planMessages']> => {
  return planMessages.map((pm) => ({
    ...pm,
    text: capString(pm.text, maxTextLength),
    userResponse: pm.userResponse ? capString(pm.userResponse, 2000) : pm.userResponse,
  }))
}

/**
 * Prune a message for localStorage storage by removing heavy fields that
 * can be fetched from the backend on demand, stripping thinking step
 * content, and capping plan message text.
 *
 * KEEPS (Essential for UI):
 * - Core message fields (id, role, content, timestamp, messageType)
 * - thinkingSteps (stripped: content removed, deep research steps dropped)
 * - planMessages (capped: text 10k, userResponse 2k — cannot be refetched)
 * - enabledDataSources, messageFiles (for "Selected Data Sources")
 * - Deep research job metadata (for restoration)
 * - HITL/prompt fields (for interaction state)
 * - Other message type data (status, file, error, banner data)
 *
 * REMOVES (Can fetch from backend via importStreamOnly):
 * - reportContent, citations, deepResearchTodos, deepResearchLLMSteps,
 *   deepResearchAgents, deepResearchToolCalls, deepResearchFiles
 * - intermediateSteps (legacy, unused)
 * - thinkingStep content/rawPayload (never displayed in ChatThinking)
 * - Deep research thinking steps (refetched from async API)
 */
export const pruneMessageForStorage = (message: ChatMessage): ChatMessage => {
  const {
    reportContent: _reportContent,
    citations: _citations,
    deepResearchTodos: _deepResearchTodos,
    deepResearchLLMSteps: _deepResearchLLMSteps,
    deepResearchAgents: _deepResearchAgents,
    deepResearchToolCalls: _deepResearchToolCalls,
    deepResearchFiles: _deepResearchFiles,
    intermediateSteps: _intermediateSteps,
    ...prunedMessage
  } = message

  if (prunedMessage.thinkingSteps?.length) {
    prunedMessage.thinkingSteps = stripThinkingStepsForStorage(prunedMessage.thinkingSteps)
  }

  if (prunedMessage.planMessages?.length) {
    prunedMessage.planMessages = prunePlanMessages(prunedMessage.planMessages)
  }

  return prunedMessage
}
