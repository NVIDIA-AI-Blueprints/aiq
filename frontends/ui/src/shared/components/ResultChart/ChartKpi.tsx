// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react'
import type { ChartKpi } from './types'

/** Headline KPI tiles, shared by the full chart (above the plot) and the standalone card. */
export const KpiTiles: FC<{ kpis: ChartKpi[] }> = ({ kpis }) =>
  kpis.length === 0 ? null : (
    <div className="result-chart-kpis">
      {kpis.map((kpi, i) => (
        <div key={i} className={`result-chart-kpi tone-${kpi.tone ?? 'default'}`}>
          <span className="result-chart-kpi-k">{kpi.label}</span>
          <span className="result-chart-kpi-v">{kpi.value}</span>
          {kpi.sub && <span className="result-chart-kpi-s">{kpi.sub}</span>}
        </div>
      ))}
    </div>
  )

/**
 * A KPI-only card (tiles + caption, no plot) for a result that is not worth a
 * chart: a single value or a one-entity result. Keeps the headline visual
 * without a misleading bar.
 */
export const ChartKpiCard: FC<{ kpis: ChartKpi[]; title?: string; subtitle?: string }> = ({
  kpis,
  title,
  subtitle,
}) => (
  <figure className="result-chart result-chart--kpi-only" aria-label={title ?? 'Result'}>
    <KpiTiles kpis={kpis} />
    {title && (
      <figcaption className="result-chart-head">
        <span className="result-chart-title">{title}</span>
        {subtitle && <span className="result-chart-sub">{subtitle}</span>}
      </figcaption>
    )}
  </figure>
)
