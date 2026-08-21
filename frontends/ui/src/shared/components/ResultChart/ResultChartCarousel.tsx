// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type FC, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from '@/adapters/ui/icons'
import { ResultChart } from './ResultChart'
import type { ChartCarouselSpec } from './types'

/** A pageable set of related line charts (e.g. several peers' trends over time). */
export const ResultChartCarousel: FC<{ spec: ChartCarouselSpec }> = ({ spec }) => {
  const [index, setIndex] = useState(0)
  const count = spec.charts.length

  useEffect(() => {
    setIndex((current) => Math.min(current, count - 1))
  }, [count])

  const previous = () => setIndex((current) => (current - 1 + count) % count)
  const next = () => setIndex((current) => (current + 1) % count)
  const active = Math.min(index, count - 1)

  return (
    <section className="result-chart-carousel" aria-label={spec.title}>
      <div className="result-chart-carousel-head">
        <span className="result-chart-carousel-title">{spec.title}</span>
        <div className="result-chart-carousel-controls">
          <button
            type="button"
            className="result-chart-carousel-button"
            aria-label="Previous chart"
            title="Previous chart"
            onClick={previous}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="result-chart-carousel-count" aria-live="polite">
            {active + 1} / {count}
          </span>
          <button
            type="button"
            className="result-chart-carousel-button"
            aria-label="Next chart"
            title="Next chart"
            onClick={next}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <ResultChart spec={spec.charts[active]} />
    </section>
  )
}
