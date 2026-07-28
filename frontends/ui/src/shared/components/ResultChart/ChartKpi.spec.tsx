// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { render, screen } from '@/test-utils'
import { ChartKpiCard, KpiTiles } from './ChartKpi'

describe('KpiTiles', () => {
  test('renders nothing when empty', () => {
    const { container } = render(<KpiTiles kpis={[]} />)
    expect(container.querySelector('.result-chart-kpis')).toBeNull()
  })

  test('renders a tile per kpi with tone and optional sub', () => {
    const { container } = render(
      <KpiTiles
        kpis={[
          { label: 'Churn', value: '12%', sub: 'next quarter', tone: 'alarm' },
          { label: 'Count', value: '5' },
        ]}
      />,
    )
    expect(container.querySelectorAll('.result-chart-kpi')).toHaveLength(2)
    expect(container.querySelector('.tone-alarm')).not.toBeNull()
    expect(container.querySelector('.tone-default')).not.toBeNull()
    expect(screen.getByText('next quarter')).toBeInTheDocument()
  })
})

describe('ChartKpiCard', () => {
  test('shows a caption when a title is given', () => {
    render(<ChartKpiCard kpis={[{ label: 'A', value: '1' }]} title="Result" subtitle="dataset" />)
    expect(screen.getByText('Result')).toBeInTheDocument()
    expect(screen.getByText('dataset')).toBeInTheDocument()
  })

  test('omits the caption without a title', () => {
    const { container } = render(<ChartKpiCard kpis={[{ label: 'A', value: '1' }]} />)
    expect(container.querySelector('.result-chart-head')).toBeNull()
  })
})
