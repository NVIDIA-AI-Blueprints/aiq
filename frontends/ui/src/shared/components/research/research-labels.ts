// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Research labels: the single source of truth for human-readable agent / tool
 * copy. The UI never shows a raw backend name; it asks this module for a title,
 * a blurb, a kind (for icon + accent), and a short argument summary instead.
 */

import { titleCaseWords } from '@/shared/lib/humanize'
import type { SourceKind } from '@/shared/components/Sources/types'
import type { NodeState } from './StatusDot'

interface AgentLabel {
  /** Short present-participle headline (e.g. "Researching"). */
  title: string
  /** One-line explanation of what the agent is doing. */
  blurb: string
}

const AGENT_LABELS: Record<string, AgentLabel> = {
  'source-router-agent': {
    title: 'Routing sources',
    blurb: 'Choosing which sources can answer the question',
  },
  'planner-agent': {
    title: 'Planning',
    blurb: 'Breaking the question into research steps',
  },
  researcher: {
    title: 'Researching',
    blurb: 'Gathering and reading sources',
  },
  'researcher-agent': {
    title: 'Researching',
    blurb: 'Gathering and reading sources',
  },
  'writer-agent': {
    title: 'Writing the report',
    blurb: 'Synthesizing findings into the final answer',
  },
}

/**
 * Human-readable label for an agent / workflow node. Falls back to a title-cased
 * version of the name with any trailing "-agent" suffix dropped.
 */
export const getAgentLabel = (name: string): AgentLabel => {
  const known = AGENT_LABELS[name]
  if (known) return known
  return { title: titleCaseWords(name.replace(/-agent$/, '')), blurb: '' }
}

interface ToolLabel {
  label: string
  kind: SourceKind
}

const TOOL_LABELS: Record<string, ToolLabel> = {
  write_todos: { label: 'Planning tasks', kind: 'doc' },
  task: { label: 'Delegating a sub-task', kind: 'doc' },
  lookup_source_catalog: { label: 'Browsing data sources', kind: 'doc' },
  write_file: { label: 'Writing a file', kind: 'doc' },
  read_file: { label: 'Reading a file', kind: 'doc' },
  ls: { label: 'Listing files', kind: 'doc' },
  edit_file: { label: 'Editing a file', kind: 'doc' },
  grep: { label: 'Searching files', kind: 'doc' },
  glob: { label: 'Finding files', kind: 'doc' },
  run_research_batch: { label: 'Running research', kind: 'doc' },
  web_search_tool: { label: 'Searching the web', kind: 'web' },
  advanced_web_search_tool: { label: 'Searching the web (advanced)', kind: 'web' },
  paper_search_tool: { label: 'Searching papers', kind: 'doc' },
  knowledge_search: { label: 'Searching the knowledge base', kind: 'doc' },
  get_verified_sources: { label: 'Finding verified sources', kind: 'doc' },
  think: { label: 'Reasoning', kind: 'doc' },
}

/**
 * Normalize a raw tool name to its lookup key: lowercase, drop a leading
 * "tool:" announcement prefix, and collapse a single leading "<group>__"
 * function-group prefix when the full name is not itself a recognized tool.
 */
const normalizeToolName = (name: string): string => {
  let normalized = (name || '').toLowerCase().trim().replace(/^tool:\s*/, '')
  if (TOOL_LABELS[normalized]) return normalized
  const prefixed = normalized.match(/^[a-z0-9]+__(.+)$/)
  if (prefixed && !TOOL_LABELS[normalized]) {
    normalized = prefixed[1]
  }
  return normalized
}

/**
 * Display form of a model id: the final path segment, fully upper-cased
 * (e.g. "azure/openai/gpt-5.2" -> "GPT-5.2", "gpt-oss-120b" -> "GPT-OSS-120B").
 * Model names read as identifiers, so they are shown in all caps rather than
 * title-cased.
 */
export const formatModelName = (name: string): string => {
  const base = (name || '').includes('/') ? (name.split('/').pop() ?? name) : name
  return base.toUpperCase()
}

/**
 * Human-readable label + source kind for a tool node. Falls back to a
 * title-cased name with a generic 'doc' kind.
 */
export const getToolLabel = (name: string): ToolLabel => {
  name = (name || '').replace(/^<+|>+$/g, '')
  const raw = name.toLowerCase().trim().replace(/^tool:\s*/, '')
  if (TOOL_LABELS[raw]) return TOOL_LABELS[raw]
  const normalized = normalizeToolName(name)
  if (TOOL_LABELS[normalized]) return TOOL_LABELS[normalized]
  // Agent / workflow nodes (e.g. "researcher", "writer-agent") show their human
  // agent title so the inline trace reads the same as the research panel.
  if (AGENT_LABELS[raw] || /-agent$/.test(raw) || raw === 'researcher') {
    return { label: getAgentLabel(raw).title, kind: 'doc' }
  }
  const base = name.includes('/') ? (name.split('/').pop() ?? name) : name
  const looksLikeModel = name.includes('/') || (base.includes('-') && !/[_\s]/.test(base))
  return { label: looksLikeModel ? formatModelName(name) : titleCaseWords(base), kind: 'doc' }
}

/**
 * Whether a function name maps to a recognized tool (one in TOOL_LABELS, e.g.
 * web_search_tool, paper_search_tool). Agents, model/LLM nodes, and folded
 * reasoning steps are not tools. Used by the trace to dedupe a tool that
 * surfaces more than once without touching non-tool rows.
 */
export const isKnownTool = (name: string): boolean => {
  const raw = (name || '').replace(/^<+|>+$/g, '').toLowerCase().trim().replace(/^tool:\s*/, '')
  return Boolean(TOOL_LABELS[raw] || TOOL_LABELS[normalizeToolName(name)])
}

const ARG_KEYS = [
  'question',
  'query',
  'search_query',
  'prompt',
  'description',
  'file_path',
  'filename',
  'path',
  'pattern',
  'content',
] as const

const MAX_ARG_LEN = 240

const truncate = (text: string): string => {
  const trimmed = text.replace(/\s+/g, ' ').trim()
  if (trimmed.length <= MAX_ARG_LEN) return trimmed
  return trimmed.slice(0, MAX_ARG_LEN - 1).trimEnd() + '…'
}

/** Leading ```json / ```python fence + trailing fence, so we can read the body. */
const CODE_FENCE = /^```[a-z]*\s*|\s*```$/gi

/** Signatures of a raw LLM message / prompt dump that carries no useful "input". */
const DUMP_SIGNATURE = /messages\s*=|SystemMessage|HumanMessage|AIMessage|TextContent|ChatContentType|\bMessage\(/

const unescapeQuotedValue = (value: string): string => value.replace(/\\([\\"'])/g, '$1')

/** Pull one quoted string field from JSON or a Python-dict-style payload. */
const extractStringField = (text: string, key: string): string | undefined => {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const doubleQuoted = text.match(
    new RegExp(`["']${escapedKey}["']\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`)
  )
  if (doubleQuoted) return unescapeQuotedValue(doubleQuoted[1]).trim()

  const singleQuoted = text.match(
    new RegExp(`["']${escapedKey}["']\\s*:\\s*'((?:\\\\.|[^'\\\\])*)'`)
  )
  if (singleQuoted) return unescapeQuotedValue(singleQuoted[1]).trim()
  return undefined
}

/** Pull the value of the first known arg key out of a json/dict-ish string. */
const extractField = (text: string): string | undefined => {
  for (const key of ARG_KEYS) {
    const value = extractStringField(text, key)
    if (value) return value
  }
  return undefined
}

/**
 * Short, human summary of a tool's INPUT for a secondary trace line: a few
 * relevant words (a file path, a query), never a raw JSON / python / message
 * dump. Reads structured input directly; for the inline payload string it strips
 * code fences and pulls out a known field. Returns undefined when there is
 * nothing readable to show (e.g. an LLM messages array).
 */
export const getToolArgSummary = (
  name: string,
  input?: Record<string, unknown> | string
): string | undefined => {
  if (input == null) return undefined

  if (typeof input === 'object') {
    for (const key of ARG_KEYS) {
      const value = input[key]
      if (typeof value !== 'string' || !value.trim()) continue
      return truncate(value)
    }
    return undefined
  }

  let text = input.trim()
  if (!text) return undefined
  const markerMatch = text.match(/(?:Function Input:|Input:)\s*([\s\S]+)/i)
  if (markerMatch) text = markerMatch[1].trim()
  text = text.replace(CODE_FENCE, '').trim()

  const field = extractField(text)
  if (field) return truncate(field)
  // A messages/prompt dump or an unparseable dict has nothing readable to show.
  if (DUMP_SIGNATURE.test(text) || text.startsWith('{') || text.startsWith('[')) return undefined
  return truncate(text) || undefined
}

/** Map a streaming agent/tool status to a trace NodeState. */
export const statusToNodeState = (s: 'running' | 'complete' | 'error'): NodeState => {
  if (s === 'complete') return 'done'
  if (s === 'error') return 'error'
  return 'running'
}

/** Map a todo-item status to a trace NodeState. */
export const todoStatusToNodeState = (
  s: 'pending' | 'in_progress' | 'completed' | 'stopped'
): NodeState => {
  switch (s) {
    case 'in_progress':
      return 'running'
    case 'completed':
      return 'done'
    case 'stopped':
      return 'interrupted'
    default:
      return 'pending'
  }
}
