// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { fireEvent, render, screen } from '@/test-utils'
import { ResultChartCarousel } from './ResultChartCarousel'
import type { ChartCarouselSpec, ChartSpec } from './types'

const line = (title: string): ChartSpec => ({
  type: 'line',
  title,
  x: { key: 'c' },
  series: [{ key: 'v' }],
  data: [
    { c: 'jan', v: 1 },
    { c: 'feb', v: 2 },
  ],
})

const spec = { title: 'Peer trends', charts: [line('One'), line('Two'), line('Three')] } as ChartCarouselSpec

describe('ResultChartCarousel', () => {
  test('renders the first chart and a position counter', () => {
    render(<ResultChartCarousel spec={spec} />)
    expect(screen.getByText('Peer trends')).toBeInTheDocument()
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
    expect(screen.getByText('One')).toBeInTheDocument()
  })

  test('pages forward and wraps around', () => {
    render(<ResultChartCarousel spec={spec} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next chart' }))
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous chart' }))
    fireEvent.click(screen.getByRole('button', { name: 'Previous chart' }))
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
    expect(screen.getByText('Three')).toBeInTheDocument()
  })

  test('clamps the index when the chart set shrinks', () => {
    const { rerender } = render(<ResultChartCarousel spec={spec} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next chart' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next chart' }))
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
    rerender(
      <ResultChartCarousel
        spec={{ title: 'Peer trends', charts: [line('One'), line('Two')] } as ChartCarouselSpec}
      />,
    )
    expect(screen.getByText('2 / 2')).toBeInTheDocument()
  })
})
