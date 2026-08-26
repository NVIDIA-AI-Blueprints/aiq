// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { inferSourceKind, prettyDomain, sourceLabel } from './source-utils'
import type { SourceRef } from './types'

/**
 * Matches a trailing references block baked into a response by the backend, e.g.
 * `\n\n**References:**\n- [1] Title - https://...`. Captures everything after the
 * heading so each `- [N] ...` line can be parsed into a {@link SourceRef}.
 */
const REFERENCES_BLOCK_RE =
  /\n{1,2}(?:\*\*References:?\*\*|#{2,3}\s+(?:References|Sources))\s*\n([\s\S]*)$/i

/** A single `- [N] ...` reference line. */
const REFERENCE_LINE_RE = /^\s*[-*]?\s*\[(\d{1,3})\]\s*(.+?)\s*$/

/** A trailing URL (web source) on a reference line, after a dash, colon, or bare space. */
const TRAILING_URL_RE = /^(.*?)\s*[-:\u2013\u2014]?\s*(https?:\/\/\S+)\s*$/i

/** A `filename, p.N` / `filename p. N` file-with-page tail. */
const FILE_PAGE_RE = /,?\s*p\.?\s*\d+\s*$/i

export interface SplitReferencesResult {
  /** The response body with the trailing references block removed. */
  body: string
  /** Sources parsed from the references block, ordered by their `[N]` index. */
  sources: SourceRef[]
}

/**
 * Parse one `- [N] ...` reference line into a {@link SourceRef}. Supports three
 * baked shapes: `Title - URL` (web), `filename, p.X` (document) and a bare
 * `tool name`. The kind/label are inferred from the URL when present, else the
 * text, reusing {@link inferSourceKind}/{@link sourceLabel}/{@link prettyDomain}.
 */
function parseReferenceLine(n: number, rest: string): SourceRef {
  const urlMatch = rest.match(TRAILING_URL_RE)
  if (urlMatch) {
    const title = urlMatch[1].trim()
    const url = urlMatch[2].trim()
    const kind = inferSourceKind(url)
    return {
      id: `ref-${n}`,
      index: n,
      title: title || prettyDomain(url) || url,
      url,
      kind,
      label: sourceLabel(url, kind),
    }
  }

  const ref = rest.trim()
  const kind = inferSourceKind(ref)
  const isFile = FILE_PAGE_RE.test(ref) || kind === 'doc'
  return {
    id: `ref-${n}`,
    index: n,
    title: ref || `Source ${n}`,
    kind: isFile ? 'doc' : kind,
    label: isFile ? ref || sourceLabel(ref, 'doc') : sourceLabel(ref, kind),
  }
}

/**
 * Split a response into its prose `body` and the structured `sources` parsed
 * from a trailing references block (`**References:**` / `## Sources`). When no
 * such block exists, `body` is the unchanged input and `sources` is empty.
 * Sources are ordered by their `[N]` index.
 */
export function splitReferences(content: string): SplitReferencesResult {
  if (!content) return { body: content ?? '', sources: [] }

  const match = content.match(REFERENCES_BLOCK_RE)
  if (!match) return { body: content, sources: [] }

  const block = match[1]
  const byIndex = new Map<number, SourceRef>()
  for (const line of block.split('\n')) {
    const lineMatch = line.match(REFERENCE_LINE_RE)
    if (!lineMatch) continue
    const n = parseInt(lineMatch[1], 10)
    if (!Number.isFinite(n) || byIndex.has(n)) continue
    byIndex.set(n, parseReferenceLine(n, lineMatch[2]))
  }

  if (byIndex.size === 0) return { body: content, sources: [] }

  const sources = [...byIndex.entries()].sort((a, b) => a[0] - b[0]).map(([, s]) => s)
  const body = content.slice(0, match.index).replace(/\s+$/, '')
  return { body, sources }
}

/**
 * A trailing References/Sources section: a heading of any level (`# Sources` ...
 * `###### Sources`) or a bold label (`**Sources**` / `**References:**`), through
 * to the end of the document.
 */
const TRAILING_REFERENCES_RE =
  /\n{1,2}(?:#{1,6}\s+(?:References|Sources)|\*\*\s*(?:References|Sources)\s*:?\s*\*\*)\s*:?\s*\n[\s\S]*$/i

/**
 * Remove a trailing References/Sources section from a body, unconditionally.
 * Unlike {@link splitReferences}, this does not require the listed lines to be
 * individually parseable. A report renders its citations as a structured source
 * list, so the writer's text `## Sources` block at the end is redundant and is
 * stripped here to avoid showing sources twice.
 */
export function stripTrailingReferences(body: string): string {
  if (!body) return body
  return body.replace(TRAILING_REFERENCES_RE, '').replace(/\s+$/, '')
}

/** A fenced code-block delimiter (```). */
const FENCE_RE = /^\s*```/

/** A short `label: value` line with no sentence punctuation. */
const ENTITY_LINE_RE = /^\s*([^:\n]{1,60}?):\s+(\S.{0,80})$/
/** Sentence-like punctuation that signals prose, not a metric line. */
const SENTENCE_PUNCT_RE = /[.!?](\s|$)/

function isEntityLine(line: string): boolean {
  const m = line.match(ENTITY_LINE_RE)
  if (!m) return false
  const [, label, value] = m
  if (SENTENCE_PUNCT_RE.test(label) || SENTENCE_PUNCT_RE.test(value)) return false
  if (label.includes('|') || value.includes('|')) return false
  return true
}

function escapeCell(text: string): string {
  return text.trim().replace(/\|/g, '\\|')
}

/**
 * Conservatively reflow runs of 2+ consecutive `label: value` lines (entity /
 * metric lists like `team_051: ~11,285 jobs`) into a 2-column GFM table so they
 * render as a scannable grid instead of flat lines. Anything that looks like a
 * sentence, a list item, or a heading is left untouched. Tightly gated to avoid
 * mangling prose.
 */
export function tabularizeEntityLines(body: string): string {
  if (!body || !body.includes(':')) return body

  const lines = body.split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    // Copy fenced code blocks through verbatim so their JSON `"key": value`
    // lines are never reflowed into a table.
    if (FENCE_RE.test(lines[i])) {
      out.push(lines[i])
      i++
      while (i < lines.length && !FENCE_RE.test(lines[i])) {
        out.push(lines[i])
        i++
      }
      if (i < lines.length) {
        out.push(lines[i])
        i++
      }
      continue
    }
    const isMarkup =
      /^\s*[-*+]\s/.test(lines[i]) || /^\s*#{1,6}\s/.test(lines[i]) || /^\s*\d+\.\s/.test(lines[i])
    if (!isMarkup && isEntityLine(lines[i])) {
      let j = i
      while (
        j < lines.length &&
        !/^\s*[-*+]\s/.test(lines[j]) &&
        !/^\s*#{1,6}\s/.test(lines[j]) &&
        !/^\s*\d+\.\s/.test(lines[j]) &&
        isEntityLine(lines[j])
      ) {
        j++
      }
      const run = lines.slice(i, j)
      if (run.length >= 2) {
        out.push('| Item | Value |')
        out.push('| --- | --- |')
        for (const line of run) {
          const m = line.match(ENTITY_LINE_RE) as RegExpMatchArray
          out.push(`| ${escapeCell(m[1])} | ${escapeCell(m[2])} |`)
        }
        i = j
        continue
      }
    }
    out.push(lines[i])
    i++
  }

  return out.join('\n')
}
