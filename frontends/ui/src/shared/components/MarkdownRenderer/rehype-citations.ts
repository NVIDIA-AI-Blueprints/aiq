// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { SKIP, visit } from 'unist-util-visit'
import type { Element, Root, Text } from 'hast'

const CITATION_RE = /\[(\d{1,3})\]/g

/**
 * Rehype plugin that rewrites inline `[n]` markers in text into `<cite>` elements
 * whose sole child is the number. The renderer maps `<cite>` to a citation chip;
 * the number is read back from the child so it survives react-markdown's
 * prop handling without relying on custom attributes.
 */
export function rehypeCitations() {
  return (tree: Root): void => {
    visit(tree, 'text', (node: Text, index, parent) => {
      if (parent == null || index == null || !node.value.includes('[')) return undefined
      const tag = (parent as Element).tagName
      if (tag === 'code' || tag === 'pre') return SKIP

      const replacements: Array<Text | Element> = []
      let lastIndex = 0
      let match: RegExpExecArray | null
      CITATION_RE.lastIndex = 0
      while ((match = CITATION_RE.exec(node.value)) !== null) {
        const prevChar = match.index > 0 ? node.value[match.index - 1] : ''
        if (/\w/.test(prevChar)) continue
        if (match.index > lastIndex) {
          replacements.push({ type: 'text', value: node.value.slice(lastIndex, match.index) })
        }
        replacements.push({
          type: 'element',
          tagName: 'cite',
          properties: {},
          children: [{ type: 'text', value: match[1] }],
        })
        lastIndex = CITATION_RE.lastIndex
      }

      if (replacements.length === 0) return undefined
      if (lastIndex < node.value.length) {
        replacements.push({ type: 'text', value: node.value.slice(lastIndex) })
      }

      parent.children.splice(index, 1, ...replacements)
      return index + replacements.length
    })
  }
}
