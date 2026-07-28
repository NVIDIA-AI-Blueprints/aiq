// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react'
import type { ChartSpec } from './types'

/** The chart's exact underlying rows, shown by the "Show data" toggle. */
export const ChartDataTable: FC<{ spec: ChartSpec; id?: string }> = ({ spec, id }) => {
  const columns = [spec.x.key, ...spec.series.map((s) => s.key)]
  const headers = [spec.x.label ?? spec.x.key, ...spec.series.map((s) => s.label ?? s.key)]

  return (
    <div className="result-chart-data" role="region" aria-label="Chart data" id={id}>
      <table className="result-chart-data-table">
        <thead>
          <tr>
            {headers.map((header, i) => (
              <th key={i} scope="col">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.data.map((row, ri) => (
            <tr key={ri}>
              {columns.map((key, ci) => (
                <td key={ci}>{row[key] == null ? '' : String(row[key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
