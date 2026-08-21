// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, test, vi } from 'vitest'
import { downloadCsv, specToCsv } from './export-csv'
import type { ChartSpec } from './types'

const spec: ChartSpec = {
  type: 'bar',
  title: 'Top GPU Models!',
  x: { key: 'model', label: 'Model' },
  series: [
    { key: 'count', label: 'Count' },
    { key: 'note' },
  ],
  data: [
    { model: 'H100', count: 5120, note: 'fast, hot' },
    { model: 'A "special" 100', count: null, note: 'line\nbreak' },
  ],
}

describe('specToCsv', () => {
  test('headers prefer labels then fall back to keys', () => {
    const { csv } = specToCsv(spec)
    expect(csv.split('\r\n')[0]).toBe('Model,Count,note')
  })

  test('escapes commas, quotes, and newlines; nulls become empty', () => {
    const rows = specToCsv(spec).csv.split('\r\n')
    expect(rows[1]).toBe('H100,5120,"fast, hot"')
    expect(rows[2]).toBe('"A ""special"" 100",,"line\nbreak"')
  })

  test('neutralizes spreadsheet formula injection on string cells only', () => {
    const injected: ChartSpec = {
      type: 'bar',
      title: 'Risk',
      x: { key: 'name' },
      series: [{ key: 'delta' }],
      data: [
        { name: '=HYPERLINK("evil")', delta: -30 },
        { name: '@cmd', delta: 5 },
      ],
    }
    const rows = specToCsv(injected).csv.split('\r\n')
    // Leading formula chars on text are quoted and prefixed with an apostrophe...
    expect(rows[1]).toBe('"\'=HYPERLINK(""evil"")",-30')
    expect(rows[2]).toBe("'@cmd,5")
    // ...but a real negative number is never mangled.
    expect(rows[1].endsWith(',-30')).toBe(true)
  })

  test('filename is slugified from the title', () => {
    expect(specToCsv(spec).filename).toBe('top-gpu-models.csv')
  })

  test('a title with no word characters falls back to chart.csv', () => {
    expect(specToCsv({ ...spec, title: '!!!' }).filename).toBe('chart.csv')
  })
})

describe('downloadCsv', () => {
  afterEach(() => vi.restoreAllMocks())

  test('creates a blob url, triggers a download, and revokes the url', () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    downloadCsv(spec)

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
    vi.unstubAllGlobals()
  })
})
