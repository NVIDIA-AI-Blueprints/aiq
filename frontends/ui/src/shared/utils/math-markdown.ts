// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export interface InlineMathSegment {
  type: 'text' | 'math'
  value: string
}

const PLACEHOLDER_PREFIX = '@@AIQ_MATH_PLACEHOLDER_'

function protectMatches(input: string, pattern: RegExp): { text: string; placeholders: string[] } {
  const placeholders: string[] = []
  const text = input.replace(pattern, (match) => {
    const token = `${PLACEHOLDER_PREFIX}${placeholders.length}@@`
    placeholders.push(match)
    return token
  })

  return { text, placeholders }
}

function restorePlaceholders(input: string, placeholders: string[]): string {
  return input.replace(new RegExp(`${PLACEHOLDER_PREFIX}(\\d+)@@`, 'g'), (_, index: string) => {
    const value = placeholders[Number(index)]
    return value ?? ''
  })
}

function normalizeOutsideCode(input: string): string {
  const protectedFences = protectMatches(
    input,
    /(^|\n)( {0,3}(?:`{3,}|~{3,})[^\n]*\n[\s\S]*?\n {0,3}(?:`{3,}|~{3,})[^\n]*(?=\n|$))/g
  )
  const protectedInlineCode = protectMatches(protectedFences.text, /(`+)([\s\S]*?)\1/g)

  const normalized = protectedInlineCode.text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, expression: string) => `$$${expression.trim()}$$`)
    .replace(/\\\((.+?)\\\)/g, (_, expression: string) => `$${expression.trim()}$`)

  return restorePlaceholders(
    restorePlaceholders(normalized, protectedInlineCode.placeholders),
    protectedFences.placeholders
  )
}

export function normalizeMathDelimiters(markdown: string): string {
  if (!markdown.includes('\\(') && !markdown.includes('\\[')) {
    return markdown
  }

  return normalizeOutsideCode(markdown)
}

export function getDisplayMath(markdown: string): string | null {
  const trimmed = markdown.trim()
  const match = trimmed.match(/^\$\$([\s\S]+)\$\$$/)

  return match ? match[1].trim() : null
}

export function splitInlineMath(text: string): InlineMathSegment[] {
  const segments: InlineMathSegment[] = []
  let buffer = ''
  let index = 0

  const flushBuffer = () => {
    if (buffer) {
      segments.push({ type: 'text', value: buffer })
      buffer = ''
    }
  }

  while (index < text.length) {
    const char = text[index]
    const prevChar = index > 0 ? text[index - 1] : ''

    if (char !== '$' || prevChar === '\\' || text[index + 1] === '$') {
      buffer += char
      index += 1
      continue
    }

    let cursor = index + 1
    let closingIndex = -1

    while (cursor < text.length) {
      const current = text[cursor]
      const previous = cursor > 0 ? text[cursor - 1] : ''
      const next = text[cursor + 1]

      if (current === '$' && previous !== '\\' && next !== '$') {
        closingIndex = cursor
        break
      }

      cursor += 1
    }

    if (closingIndex === -1) {
      buffer += char
      index += 1
      continue
    }

    const expression = text.slice(index + 1, closingIndex).trim()

    if (!expression) {
      buffer += '$$'
      index = closingIndex + 1
      continue
    }

    flushBuffer()
    segments.push({ type: 'math', value: expression })
    index = closingIndex + 1
  }

  flushBuffer()

  return segments.length > 0 ? segments : [{ type: 'text', value: text }]
}
