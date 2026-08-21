// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { SourceStrip } from './SourceStrip'
import type { SourceRef } from './types'

function makeSources(n: number): SourceRef[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `s${i}`,
    index: i + 1,
    title: `Source ${i}`,
    kind: 'web' as const,
    label: `site${i}.com`,
    url: `https://site${i}.com`,
  }))
}

describe('SourceStrip', () => {
  test('renders nothing when there are no sources', () => {
    const { container } = render(<SourceStrip sources={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  test('renders a row for every source with no hidden-by-default truncation', () => {
    render(<SourceStrip sources={makeSources(30)} />)
    expect(screen.getByText('Source 0')).toBeInTheDocument()
    expect(screen.getByText('Source 29')).toBeInTheDocument()
    expect(screen.queryByText(/more/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  test('renders one link per source pointing at its url', () => {
    render(<SourceStrip sources={makeSources(3)} />)
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(3)
    expect(links[0]).toHaveAttribute('href', 'https://site0.com')
    expect(links[0]).toHaveAttribute('target', '_blank')
    expect(links[2]).toHaveAttribute('href', 'https://site2.com')
  })

  test('labels each row by its real [N] marker, not its array position', () => {
    const sparse: SourceRef[] = [
      { id: 'a', index: 2, title: 'Second', kind: 'web', label: 'two.com', url: 'https://two.com' },
      { id: 'b', index: 5, title: 'Fifth', kind: 'web', label: 'five.com', url: 'https://five.com' },
    ]
    render(<SourceStrip sources={sparse} />)
    expect(screen.getByText('[2]')).toBeInTheDocument()
    expect(screen.getByText('[5]')).toBeInTheDocument()
    expect(screen.queryByText('[1]')).not.toBeInTheDocument()
  })
})
