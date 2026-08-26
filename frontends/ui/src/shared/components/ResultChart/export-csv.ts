// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ChartCell, ChartSpec } from './types'

/** Leading characters a spreadsheet may execute as a formula. */
const FORMULA_TRIGGER = /^[=+\-@\t\r]/

/**
 * Serialize a cell to a CSV field: neutralize spreadsheet formula injection on
 * string cells (a leading `=`/`+`/`-`/`@` text becomes an inert `'`-prefixed
 * string), then quote per RFC 4180 when the field holds a comma, quote, or
 * newline. Numeric cells pass through so real negatives are never mangled.
 */
function escapeField(value: ChartCell): string {
  if (value == null) return ''
  let text = String(value)
  if (typeof value === 'string' && FORMULA_TRIGGER.test(text)) text = `'${text}`
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

/** Slugify a chart title into a safe `.csv` filename. */
function toFilename(title: string): string {
  const slug = title
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `${slug || 'chart'}.csv`
}

/**
 * Serialize a chart spec's exact data rows to an RFC 4180 CSV. Columns are the x
 * key followed by each series key; headers prefer human labels. Values are the
 * same ones the chart plots, so the export is faithful by construction.
 */
export function specToCsv(spec: ChartSpec): { filename: string; csv: string } {
  const columns = [spec.x.key, ...spec.series.map((s) => s.key)]
  const headers = [spec.x.label ?? spec.x.key, ...spec.series.map((s) => s.label ?? s.key)]

  const lines = [headers.map(escapeField).join(',')]
  for (const row of spec.data) {
    lines.push(columns.map((key) => escapeField(row[key] ?? null)).join(','))
  }

  return { filename: toFilename(spec.title), csv: lines.join('\r\n') }
}

/**
 * Trigger a browser download of the spec's CSV. Kept thin and separate from
 * {@link specToCsv} so the serialization stays pure and unit-testable.
 */
export function downloadCsv(spec: ChartSpec): void {
  const { filename, csv } = specToCsv(spec)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
