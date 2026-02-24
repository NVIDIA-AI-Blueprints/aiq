// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Intermediate Step Parser
 *
 * Utilities for parsing and processing intermediate step messages
 * from the WebSocket backend (NAT protocol).
 *
 * Categories are maintained for data organization and potential future features,
 * but are not used for UI display in the current ChatThinking component.
 */

import type { IntermediateStepCategory } from '../types'

/**
 * Mapping of function names to their data categories.
 * Used for persistence and data organization.
 */
const CATEGORY_MAP: Record<string, IntermediateStepCategory> = {
  '<workflow>': 'tasks',
  intent_classifier: 'agents',
  depth_router: 'agents',
  shallow_research_agent: 'agents',
  deep_research_agent: 'agents',
  meta_chatter: 'agents',
  chat_deepresearcher_agent: 'agents',
  web_search_tool: 'tools',
  tavily_search: 'tools',
}

/**
 * Default category for unknown function names
 */
const DEFAULT_CATEGORY: IntermediateStepCategory = 'agents'

/**
 * Result of parsing a function name from the backend
 */
export interface ParsedFunctionName {
  /** The raw function name (e.g., "web_search_tool") */
  functionName: string
  /** Whether this is a "Function Start" (false) or "Function Complete" (true) */
  isComplete: boolean
}

/**
 * Parse the function name and status from the backend message name.
 * Backend format: "Function Start: <function_name>" or "Function Complete: <function_name>"
 *
 * @param name - The raw name field from backend (e.g., "Function Start: web_search_tool")
 * @returns Parsed function name and completion status
 */
export const parseFunctionName = (name: string): ParsedFunctionName => {
  // Match patterns like "Function Start: xyz" or "Function Complete: xyz"
  const startMatch = name.match(/^Function Start:\s*(.+)$/i)
  if (startMatch) {
    return {
      functionName: startMatch[1].trim(),
      isComplete: false,
    }
  }

  const completeMatch = name.match(/^Function Complete:\s*(.+)$/i)
  if (completeMatch) {
    return {
      functionName: completeMatch[1].trim(),
      isComplete: true,
    }
  }

  // Fallback: treat the whole name as the function name
  return {
    functionName: name.trim(),
    isComplete: false,
  }
}

/**
 * Map a function name to its data category for persistence.
 *
 * @param functionName - The function name (e.g., "web_search_tool")
 * @returns The category for data organization
 */
export const mapFunctionToCategory = (functionName: string): IntermediateStepCategory => {
  return CATEGORY_MAP[functionName] ?? DEFAULT_CATEGORY
}

/**
 * Check if a name represents an LLM model rather than a function/tool.
 * LLM models typically have format: "provider/org/model-name" or contain slashes.
 *
 * @param name - The name to check (e.g., "nvidia/nvidia/Nemotron-3-Nano-30B-A3B")
 * @returns True if this appears to be an LLM model name
 */
export const isLLMModel = (name: string): boolean => {
  return name.includes('/') && !name.startsWith('Function') && !name.startsWith('Tool:')
}

/**
 * Check if a name has the "Tool:" prefix (LLM announcing tool call).
 *
 * @param name - The name to check (e.g., "Tool: web_search_tool")
 * @returns True if this has the "Tool:" prefix
 */
export const hasToolPrefix = (name: string): boolean => {
  return name.startsWith('Tool:')
}

/**
 * Whether the backend step name is a top-level function (Function Start/Complete).
 * Such steps are shown as main list items; others (model, Tool: ...) are shown indented.
 */
export const isFunctionStepName = (rawName: string): boolean => {
  return /^Function (Start|Complete):/i.test(rawName?.trim() ?? '')
}

/**
 * Display name for the root workflow step (chat_deepresearcher_agent).
 * Shown as "Workflow: Chat Researcher" instead of a raw function name.
 */
export const getWorkflowDisplayName = (functionName: string): string => {
  if (functionName === 'chat_deepresearcher_agent') {
    return 'Workflow: Chat Researcher'
  }
  return ''
}

/**
 * Convert a snake_case or special function name to a human-readable display name.
 * Also handles LLM model names and tool prefixes.
 *
 * @param functionName - The raw function name (e.g., "web_search_tool", "<workflow>", "nvidia/nvidia/Nemotron-3-Nano-30B-A3B")
 * @returns Human-readable name (e.g., "Web Search Tool", "Workflow", "Nemotron 3 Nano 30B")
 */
export const getDisplayName = (functionName: string): string => {
  if (functionName === 'chat_deepresearcher_agent') {
    return 'Chat Researcher'
  }
  // Handle special case for workflow
  if (functionName === '<workflow>') {
    return 'Workflow'
  }

  // Handle LLM model names (e.g., "nvidia/nvidia/Nemotron-3-Nano-30B-A3B")
  if (isLLMModel(functionName)) {
    const parts = functionName.split('/')
    const modelName = parts[parts.length - 1] // Take last segment
    // Clean up: convert hyphens to spaces, capitalize
    return modelName
      .split('-')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  }

  // Handle "Tool:" prefix (strip it off)
  const cleaned = functionName.replace(/^Tool:\s*/i, '')

  // Convert snake_case to Title Case
  return cleaned
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

/**
 * Clean up and format the payload content for storage/display.
 * Removes excessive markdown formatting and Python repr noise.
 *
 * @param payload - The raw payload string from backend
 * @returns Cleaned and formatted content
 */
export const formatPayload = (payload: string): string => {
  if (!payload) return ''

  let cleaned = payload

  // Remove "**Function Input:**" and "**Function Output:**" headers
  cleaned = cleaned.replace(/\*\*Function Input:\*\*/gi, '')
  cleaned = cleaned.replace(/\*\*Function Output:\*\*/gi, '')

  // Remove code block markers for python/json
  cleaned = cleaned.replace(/```(?:python|json)?\n?/gi, '')
  cleaned = cleaned.replace(/```/g, '')

  // Decode HTML entities
  cleaned = cleaned.replace(/&lt;/g, '<')
  cleaned = cleaned.replace(/&gt;/g, '>')
  cleaned = cleaned.replace(/&amp;/g, '&')
  cleaned = cleaned.replace(/&quot;/g, '"')
  cleaned = cleaned.replace(/&#39;/g, "'")

  // Clean up Python repr formatting (e.g., "type=<ChatContentType.TEXT: 'text'>")
  cleaned = cleaned.replace(/<\w+\.\w+:\s*'[^']*'>/g, (match) => {
    // Extract the value part (e.g., 'text' from "<ChatContentType.TEXT: 'text'>")
    const valueMatch = match.match(/:\s*'([^']*)'/)
    return valueMatch ? `'${valueMatch[1]}'` : match
  })

  // Trim whitespace
  cleaned = cleaned.trim()

  return cleaned
}
