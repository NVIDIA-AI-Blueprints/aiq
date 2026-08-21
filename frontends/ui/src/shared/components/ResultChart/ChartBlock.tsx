// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type FC, type ReactNode, useMemo } from 'react'
import { parseCarouselSpec, parseChartSpec, parseKpiSpec } from './parse'
import { degenerateKpis, normalizeChart } from './normalize'
import { ResultChart } from './ResultChart'
import { ResultChartCarousel } from './ResultChartCarousel'
import { ChartKpiCard } from './ChartKpi'

/**
 * Render a ```chart / ```chart-carousel fenced block. A full spec draws the
 * interactive chart, unless it conveys no comparison (a single value or a
 * near-constant metric), which renders as a KPI card instead. A KPI-only block
 * renders as a card. Anything malformed falls back to the raw block.
 */
export const ChartBlock: FC<{ raw: string; fallback?: ReactNode }> = ({ raw, fallback = null }) => {
  return useMemo<ReactNode>(() => {
    const carousel = parseCarouselSpec(raw)
    if (carousel) return <ResultChartCarousel spec={carousel} />

    const spec = parseChartSpec(raw)
    if (spec) {
      const kpis = degenerateKpis(spec)
      if (kpis) return <ChartKpiCard title={spec.title} subtitle={spec.subtitle} kpis={kpis} />
      const { spec: normalized, truncation } = normalizeChart(spec)
      return <ResultChart spec={normalized} truncation={truncation} />
    }

    const kpiOnly = parseKpiSpec(raw)
    if (kpiOnly) return <ChartKpiCard title={kpiOnly.title} subtitle={kpiOnly.subtitle} kpis={kpiOnly.kpis} />

    return fallback
  }, [raw, fallback])
}
