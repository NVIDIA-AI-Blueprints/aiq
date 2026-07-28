// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen } from '@/test-utils'
import { ResultChart } from './ResultChart'
import type { ChartSpec } from './types'

function spec(overrides: Partial<ChartSpec> = {}): ChartSpec {
  return {
    type: 'bar',
    title: 'Fleet',
    subtitle: 'gpu',
    x: { key: 'model' },
    series: [{ key: 'count' }],
    data: [
      { model: 'H100', count: 10 },
      { model: 'A100', count: 20 },
    ],
    ...overrides,
  } as ChartSpec
}

describe('ResultChart', () => {
  afterEach(() => vi.restoreAllMocks())

  test('renders an accessible figure with title and subtitle', () => {
    render(<ResultChart spec={spec()} />)
    expect(screen.getByRole('img', { name: /bar chart: Fleet/ })).toBeInTheDocument()
    expect(screen.getByText('Fleet')).toBeInTheDocument()
    expect(screen.getByText('gpu')).toBeInTheDocument()
  })

  test('shows a legend only for multi-series charts', () => {
    const { container, rerender } = render(<ResultChart spec={spec()} />)
    expect(container.querySelector('.result-chart-legend')).toBeNull()
    rerender(
      <ResultChart
        spec={spec({
          type: 'grouped-bar',
          series: [{ key: 'count' }, { key: 'other', label: 'Other' }],
          data: [{ model: 'H100', count: 10, other: 5 }],
        })}
      />,
    )
    expect(container.querySelector('.result-chart-legend')).not.toBeNull()
    expect(screen.getByText('Other')).toBeInTheDocument()
  })

  test('renders horizontal, delta, line and area variants', () => {
    for (const type of ['hbar', 'delta', 'line', 'area'] as const) {
      const { container } = render(
        <ResultChart spec={spec({ type, data: [{ model: 'a', count: 5 }, { model: 'b', count: -3 }] })} />,
      )
      expect(container.querySelector('svg')).not.toBeNull()
    }
  })

  test('shows and hides a tooltip on hover', () => {
    const { container } = render(<ResultChart spec={spec()} />)
    const bar = container.querySelector('.result-chart-bar') as SVGElement
    fireEvent.mouseMove(bar, { clientX: 5, clientY: 5 })
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    fireEvent.mouseLeave(bar)
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  test('positions the tooltip safely when no bounding rect is available', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      undefined as unknown as DOMRect,
    )
    const { container } = render(<ResultChart spec={spec()} />)
    const bar = container.querySelector('.result-chart-bar') as SVGElement
    fireEvent.mouseMove(bar, { clientX: 7, clientY: 9 })
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  test('renders headline KPIs and a truncation note', () => {
    render(
      <ResultChart
        spec={spec({ kpis: [{ label: 'Total', value: '30' }] })}
        truncation={{ shown: 15, total: 40 }}
      />,
    )
    expect(screen.getByText('Total')).toBeInTheDocument()
    expect(screen.getByText('Showing top 15 of 40')).toBeInTheDocument()
  })

  test('toggles the underlying data table', () => {
    render(<ResultChart spec={spec()} />)
    expect(screen.queryByRole('region', { name: 'Chart data' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Show data' }))
    expect(screen.getByRole('region', { name: 'Chart data' })).toBeInTheDocument()
  })

  test('references the data region only while it is mounted', () => {
    render(<ResultChart spec={spec()} />)
    const collapsed = screen.getByRole('button', { name: 'Show data' })
    expect(collapsed).not.toHaveAttribute('aria-controls')
    fireEvent.click(collapsed)
    const region = screen.getByRole('region', { name: 'Chart data' })
    const opened = screen.getByRole('button', { name: 'Hide data' })
    expect(opened.getAttribute('aria-controls')).toBe(region.getAttribute('id'))
  })
})
