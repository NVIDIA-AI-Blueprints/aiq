// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { render, screen, within } from '@/test-utils'
import { ChartBlock } from './ChartBlock'

const bar = {
  type: 'bar',
  title: 'Fleet',
  x: { key: 'model' },
  series: [{ key: 'count' }],
  data: [
    { model: 'H100', count: 10 },
    { model: 'A100', count: 20 },
  ],
}

describe('ChartBlock', () => {
  test('renders a chart for a valid spec', () => {
    render(<ChartBlock raw={JSON.stringify(bar)} />)
    expect(screen.getByRole('img', { name: /bar chart: Fleet/ })).toBeInTheDocument()
  })

  test('renders a carousel for a chart-carousel spec', () => {
    const line = { ...bar, type: 'line' }
    render(<ChartBlock raw={JSON.stringify({ title: 'Trends', charts: [line, line] })} />)
    expect(screen.getByLabelText('Trends')).toBeInTheDocument()
  })

  test('downgrades a degenerate chart to a KPI card', () => {
    const single = { ...bar, data: [{ model: 'H100', count: 42 }] }
    const { container } = render(<ChartBlock raw={JSON.stringify(single)} />)
    expect(container.querySelector('.result-chart--kpi-only')).not.toBeNull()
  })

  test('renders a KPI-only spec as a card', () => {
    render(<ChartBlock raw={JSON.stringify({ title: 'Churn', kpis: [{ label: 'Rate', value: '12%' }] })} />)
    expect(screen.getByText('Rate')).toBeInTheDocument()
  })

  test('a percent chart renders "94%" from both "94%" string data and 0.94 numeric data', () => {
    const pctSpec = (rate: unknown) => ({
      type: 'bar',
      title: 'On-time rate',
      x: { key: 'model' },
      y: { format: 'percent' },
      series: [{ key: 'rate' }],
      data: [{ model: 'H100', rate }],
    })
    const fromString = render(<ChartBlock raw={JSON.stringify(pctSpec('94%'))} />)
    expect(within(fromString.container).getByText('94%')).toBeInTheDocument()
    const fromNumber = render(<ChartBlock raw={JSON.stringify(pctSpec(0.94))} />)
    expect(within(fromNumber.container).getByText('94%')).toBeInTheDocument()
  })

  test('applies truncation for oversized rankings', () => {
    const data = Array.from({ length: 30 }, (_, i) => ({ model: `m${i}`, count: i }))
    render(<ChartBlock raw={JSON.stringify({ ...bar, type: 'hbar', data })} />)
    expect(screen.getByText('Showing top 15 of 30')).toBeInTheDocument()
  })

  test('falls back for a malformed spec', () => {
    render(<ChartBlock raw="{not json" fallback={<div data-testid="fallback" />} />)
    expect(screen.getByTestId('fallback')).toBeInTheDocument()
  })

  test('renders nothing when malformed and no fallback is given', () => {
    const { container } = render(<ChartBlock raw="{not json" />)
    expect(container.textContent).toBe('')
    expect(container.querySelector('figure')).toBeNull()
  })
})
