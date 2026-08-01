// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen } from '@/test-utils'
import { ChartToolbar } from './ChartToolbar'
import type { ChartSpec } from './types'

const spec: ChartSpec = {
  type: 'bar',
  title: 'Top models',
  x: { key: 'model' },
  series: [{ key: 'count' }],
  data: [{ model: 'H100', count: 10 }],
}

describe('ChartToolbar', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  test('reflects the open state, fires the toggle, and controls the data region', () => {
    const onToggleData = vi.fn()
    const { rerender } = render(
      <ChartToolbar spec={spec} dataOpen={false} dataId="chart-data-1" onToggleData={onToggleData} />,
    )
    const toggle = screen.getByRole('button', { name: 'Show data' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).not.toHaveAttribute('aria-controls')
    fireEvent.click(toggle)
    expect(onToggleData).toHaveBeenCalledOnce()

    rerender(<ChartToolbar spec={spec} dataOpen dataId="chart-data-1" onToggleData={onToggleData} />)
    const opened = screen.getByRole('button', { name: 'Hide data' })
    expect(opened).toHaveAttribute('aria-expanded', 'true')
    expect(opened).toHaveAttribute('aria-controls', 'chart-data-1')
  })

  test('download triggers a CSV blob download', () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<ChartToolbar spec={spec} dataOpen={false} dataId="chart-data-1" onToggleData={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /CSV/ }))

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
  })
})
