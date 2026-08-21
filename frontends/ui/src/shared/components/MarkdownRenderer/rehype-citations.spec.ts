// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import type { Root } from 'hast'
import { rehypeCitations } from './rehype-citations'

function paragraph(text: string): Root {
  return {
    type: 'root',
    children: [{ type: 'element', tagName: 'p', properties: {}, children: [{ type: 'text', value: text }] }],
  }
}

function runPlugin(tree: Root): Root {
  rehypeCitations()(tree)
  return tree
}

describe('rehypeCitations', () => {
  test('splits a [n] marker into text + cite + text', () => {
    const tree = runPlugin(paragraph('Users total 11,463 [1] today.'))
    const p = tree.children[0] as {
      children: Array<{ type: string; tagName?: string; value?: string; children?: Array<{ value: string }> }>
    }
    expect(p.children.map((c) => c.tagName ?? c.value)).toEqual(['Users total 11,463 ', 'cite', ' today.'])
    expect(p.children[1].children?.[0].value).toBe('1')
  })

  test('handles multiple markers', () => {
    const tree = runPlugin(paragraph('A [1] and B [12].'))
    const p = tree.children[0] as { children: Array<{ tagName?: string }> }
    expect(p.children.filter((c) => c.tagName === 'cite')).toHaveLength(2)
  })

  test('leaves text without markers untouched', () => {
    const tree = runPlugin(paragraph('No citations here.'))
    const p = tree.children[0] as { children: Array<{ value?: string }> }
    expect(p.children).toHaveLength(1)
    expect(p.children[0].value).toBe('No citations here.')
  })

  test('does not treat a subscript-style prose bracket (results[1]) as a citation', () => {
    const tree = runPlugin(paragraph('Read results[1] from the array.'))
    const p = tree.children[0] as { children: Array<{ tagName?: string; value?: string }> }
    expect(p.children.filter((c) => c.tagName === 'cite')).toHaveLength(0)
    expect(p.children).toHaveLength(1)
    expect(p.children[0].value).toBe('Read results[1] from the array.')
  })

  test('still parses a real [n] citation when the preceding bracket is prose', () => {
    const tree = runPlugin(paragraph('Read results[1] and note the total [2].'))
    const p = tree.children[0] as { children: Array<{ tagName?: string; children?: Array<{ value: string }> }> }
    const cites = p.children.filter((c) => c.tagName === 'cite')
    expect(cites).toHaveLength(1)
    expect(cites[0].children?.[0].value).toBe('2')
  })
})
