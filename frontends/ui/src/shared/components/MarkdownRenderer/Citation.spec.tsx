// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { Citation } from './Citation'
import type { SourceRef } from '@/shared/components/Sources/types'

const sources: SourceRef[] = [
  {
    id: 's1',
    index: 1,
    title: 'NVIDIA shipped record volume.',
    kind: 'web',
    label: 'nvidia.com',
    url: 'https://www.nvidia.com/news',
    snippet: 'Record shipments across the fleet.',
  },
]

describe('Citation', () => {
  test('renders the citation number with an accessible label', () => {
    render(<Citation n={1} sources={sources} />)
    expect(screen.getByLabelText('Source 1: nvidia.com')).toHaveTextContent('1')
  })

  test('renders the marker as a superscript reference mark', () => {
    render(<Citation n={1} sources={sources} />)
    const link = screen.getByLabelText('Source 1: nvidia.com')
    expect(link.querySelector('sup')).toHaveTextContent('1')
  })

  test('links to the source url', () => {
    render(<Citation n={1} sources={sources} />)
    expect(screen.getByLabelText('Source 1: nvidia.com')).toHaveAttribute(
      'href',
      'https://www.nvidia.com/news'
    )
  })

  test('a non-numeric value renders bracketed text and no chip', () => {
    render(<Citation n={Number.NaN} sources={sources} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^Source/)).not.toBeInTheDocument()
  })

  test('an out-of-range index degrades to a bare chip', () => {
    render(<Citation n={9} sources={sources} />)
    expect(screen.getByLabelText('Source 9')).toBeInTheDocument()
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  test('focus reveals a popover with the source label and title', () => {
    render(<Citation n={1} sources={sources} />)
    fireEvent.focus(screen.getByLabelText('Source 1: nvidia.com'))
    const tip = screen.getByRole('tooltip')
    expect(tip).toHaveTextContent('nvidia.com')
    expect(tip).toHaveTextContent('NVIDIA shipped record volume.')
  })

  test('resolves by real [N] marker, not array position', () => {
    const sparse: SourceRef[] = [
      { id: 'a', index: 2, title: 'Second source', kind: 'web', label: 'two.com', url: 'https://two.com' },
      { id: 'b', index: 3, title: 'Third source', kind: 'web', label: 'three.com', url: 'https://three.com' },
    ]
    render(<Citation n={2} sources={sparse} />)
    const link = screen.getByLabelText('Source 2: two.com')
    expect(link).toHaveAttribute('href', 'https://two.com')
  })

  test('resolves a marker across a gap in the numbering', () => {
    const gapped: SourceRef[] = [
      { id: 'a', index: 1, title: 'First source', kind: 'web', label: 'one.com', url: 'https://one.com' },
      { id: 'c', index: 3, title: 'Third source', kind: 'web', label: 'three.com', url: 'https://three.com' },
    ]
    render(<Citation n={3} sources={gapped} />)
    expect(screen.getByLabelText('Source 3: three.com')).toHaveAttribute('href', 'https://three.com')
  })

  test('a marker with no matching reference renders a bare chip, not the wrong source', () => {
    const gapped: SourceRef[] = [
      { id: 'a', index: 1, title: 'First source', kind: 'web', label: 'one.com', url: 'https://one.com' },
      { id: 'c', index: 3, title: 'Third source', kind: 'web', label: 'three.com', url: 'https://three.com' },
    ]
    render(<Citation n={2} sources={gapped} />)
    expect(screen.getByLabelText('Source 2')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })
})
