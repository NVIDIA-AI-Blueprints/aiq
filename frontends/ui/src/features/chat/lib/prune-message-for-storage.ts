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
 * Prune a message for localStorage storage by removing heavy fields that
 * can be fetched from the backend on demand.
 *
 * KEEPS (Essential for UI):
 * - Core message fields (id, role, content, timestamp, messageType)
 * - thinkingSteps (for ChatThinking display)
 * - planMessages (cannot be refetched - WebSocket only)
 * - enabledDataSources, messageFiles (for "Selected Data Sources")
 * - Deep research job metadata (for restoration)
 * - HITL/prompt fields (for interaction state)
 * - Other message type data (status, file, error, banner data)
 *
 * REMOVES (Can fetch from backend via importStreamOnly):
 * - reportContent (can fetch via loadReport or importStreamOnly)
 * - citations (fetch via importStreamOnly)
 * - deepResearchTodos (fetch via importStreamOnly)
 * - deepResearchLLMSteps (fetch via importStreamOnly)
 * - deepResearchAgents (fetch via importStreamOnly)
 * - deepResearchToolCalls (fetch via importStreamOnly)
 * - deepResearchFiles (fetch via importStreamOnly)
 * - intermediateSteps (legacy, unused)
 *
 * @param message - The message to prune
 * @returns Pruned message with heavy fields removed
 */
export const pruneMessageForStorage = (message: ChatMessage): ChatMessage => {
  // Create a shallow copy and explicitly remove heavy fields
  const {
    // Remove these heavy, refetchable fields
    reportContent: _reportContent,
    citations: _citations,
    deepResearchTodos: _deepResearchTodos,
    deepResearchLLMSteps: _deepResearchLLMSteps,
    deepResearchAgents: _deepResearchAgents,
    deepResearchToolCalls: _deepResearchToolCalls,
    deepResearchFiles: _deepResearchFiles,
    intermediateSteps: _intermediateSteps,
    // Keep everything else
    ...prunedMessage
  } = message

  return prunedMessage
}

/**
 * Cap string content to prevent excessively large messages.
 * Used as a safety measure for user/agent message content.
 *
 * @param value - String to cap
 * @param max - Maximum length
 * @returns Capped string
 */
export const capString = (value: string, max: number): string => {
  return value.length > max ? value.slice(0, max) : value
}

/**
 * Prune thinking steps to reduce storage size.
 * Keeps step metadata but caps content length.
 *
 * @param steps - Array of thinking steps
 * @param maxContentLength - Maximum length for step content
 * @returns Pruned thinking steps
 */
export const pruneThinkingSteps = (
  steps: NonNullable<ChatMessage['thinkingSteps']>,
  maxContentLength = 5000
): NonNullable<ChatMessage['thinkingSteps']> => {
  return steps.map((step) => ({
    ...step,
    content: capString(step.content, maxContentLength),
  }))
}

/**
 * Prune plan messages to reduce storage size.
 * Keeps plan structure but caps text content.
 *
 * @param planMessages - Array of plan messages
 * @param maxTextLength - Maximum length for plan text
 * @returns Pruned plan messages
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
