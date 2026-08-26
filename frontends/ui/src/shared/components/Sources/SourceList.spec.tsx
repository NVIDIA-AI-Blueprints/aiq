// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { describe, expect, test } from 'vitest'
import { SourceList } from './SourceList'
import type { SourceRef } from './types'

const webSource: SourceRef = {
  id: 'w1',
  index: 1,
  title: 'NVIDIA shipped record volume.',
  kind: 'web',
  label: 'nvidia.com',
  url: 'https://www.nvidia.com/news',
}

const docSource: SourceRef = {
  id: 'd1',
  index: 2,
  title: 'Internal fleet report',
  kind: 'doc',
  label: 'fleet-report.pdf',
}

describe('SourceList', () => {
  test('renders nothing when there are no sources', () => {
    render(<SourceList sources={[]} />)
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  test('renders one entry per source with its label', () => {
    render(<SourceList sources={[webSource, docSource]} />)
    expect(screen.getByText('nvidia.com').closest('a')).not.toBeNull()
    expect(screen.getByText('fleet-report.pdf')).toBeInTheDocument()
  })

  test('renders a clickable link for a web source even when the label equals the domain', () => {
    render(<SourceList sources={[{ ...webSource, label: 'www.nvidia.com/news' }]} />)
    const links = screen.getAllByRole('link')
    expect(links.length).toBeGreaterThan(0)
    expect(links[0]).toHaveAttribute('href', 'https://www.nvidia.com/news')
  })

  test('renders a doc source without a link', () => {
    render(<SourceList sources={[docSource]} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('fleet-report.pdf')).toBeInTheDocument()
  })

  test('labels each source by its real [N] marker, not its array position', () => {
    render(
      <SourceList
        sources={[
          { ...webSource, index: 2 },
          { ...docSource, index: 5 },
        ]}
      />
    )
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.queryByText('1')).not.toBeInTheDocument()
  })
})
