// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { render, screen } from '@/test-utils'
import { ChartDataTable } from './ChartDataTable'
import type { ChartSpec } from './types'

const spec: ChartSpec = {
  type: 'bar',
  title: 'T',
  x: { key: 'model', label: 'Model' },
  series: [{ key: 'count', label: 'Count' }],
  data: [
    { model: 'H100', count: 10 },
    { model: 'A100', count: null },
  ],
}

describe('ChartDataTable', () => {
  test('renders labeled headers and one row per data entry', () => {
    render(<ChartDataTable spec={spec} />)
    expect(screen.getByRole('columnheader', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Count' })).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.getByText('H100')).toBeInTheDocument()
  })

  test('renders a null cell as empty text', () => {
    const { container } = render(<ChartDataTable spec={spec} />)
    const lastRowCells = container.querySelectorAll('tbody tr:last-child td')
    expect(lastRowCells[1].textContent).toBe('')
  })
})
