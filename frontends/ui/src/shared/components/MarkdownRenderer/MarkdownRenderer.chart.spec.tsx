// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import { render, screen } from '@/test-utils'
import { MarkdownRenderer } from './MarkdownRenderer'

const chart = {
  type: 'bar',
  title: 'Fleet',
  x: { key: 'model' },
  series: [{ key: 'count' }],
  data: [
    { model: 'H100', count: 10 },
    { model: 'A100', count: 20 },
  ],
}

const fence = (lang: string, body: object) => '```' + lang + '\n' + JSON.stringify(body) + '\n```'

describe('MarkdownRenderer chart integration', () => {
  test('renders a ```chart fence as a chart, not a code block', () => {
    render(<MarkdownRenderer content={fence('chart', chart)} />)
    expect(screen.getByRole('img', { name: /bar chart: Fleet/ })).toBeInTheDocument()
  })

  test('renders a ```chart-carousel fence as a carousel', () => {
    const line = { ...chart, type: 'line' }
    render(<MarkdownRenderer content={fence('chart-carousel', { title: 'Trends', charts: [line, line] })} />)
    expect(screen.getByLabelText('Trends')).toBeInTheDocument()
  })

  test('fences and renders a bare chart-spec line', () => {
    render(<MarkdownRenderer content={`Here is the ranking:\n\n${JSON.stringify(chart)}`} />)
    expect(screen.getByRole('img', { name: /bar chart: Fleet/ })).toBeInTheDocument()
  })

  test('renders multiple charts in one answer', () => {
    const second = { ...chart, title: 'Second' }
    render(<MarkdownRenderer content={`${fence('chart', chart)}\n\n${fence('chart', second)}`} />)
    expect(screen.getByRole('img', { name: /bar chart: Fleet/ })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /bar chart: Second/ })).toBeInTheDocument()
  })

  test('an invalid chart fence falls back to a code block', () => {
    render(<MarkdownRenderer content={'```chart\n{not json\n```'} />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByText(/not json/)).toBeInTheDocument()
  })

  test('a non-chart fence is unaffected', () => {
    render(<MarkdownRenderer content={'```python\nprint(1)\n```'} />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByText(/print/)).toBeInTheDocument()
  })
})
