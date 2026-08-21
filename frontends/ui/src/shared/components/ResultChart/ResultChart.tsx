// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ResultChart renders an agent-authored {@link ChartSpec} as an interactive SVG.
 * The agent chooses the type, encodings, data and formatting; this component owns
 * the look, the scaling and the safe axis defaults, plus the show-data/export
 * toolbar and hover tooltips. Per-type geometry lives in `renderers/`; this shell
 * only maps the emitted primitive marks to SVG and wires interaction.
 */

'use client'

import { type FC, type MouseEvent, type ReactNode, useId, useMemo, useRef, useState } from 'react'
import { CHART_WIDTH, chartHeight, plotBox } from './geometry'
import { seriesColor } from './palette'
import { toNumber } from './parse'
import { computeDomain, formatValue } from './scale'
import { RENDERERS, type Mark } from './renderers'
import { ChartToolbar } from './ChartToolbar'
import { ChartDataTable } from './ChartDataTable'
import { KpiTiles } from './ChartKpi'
import type { Truncation } from './normalize'
import type { ChartSpec } from './types'

interface Tooltip {
  text: string
  x: number
  y: number
}

export const ResultChart: FC<{ spec: ChartSpec; truncation?: Truncation | null }> = ({
  spec,
  truncation = null,
}) => {
  const layout = useMemo(() => {
    const fmt = spec.y?.format ?? 'number'
    const colors = spec.series.map((s, i) => seriesColor(s.color, i))
    const values = spec.series.flatMap((s) =>
      spec.data.map((row) => toNumber(row[s.key])).filter((v): v is number => v != null),
    )
    const { min, max } = computeDomain(values, fmt === 'percent')
    const height = chartHeight(spec)
    const horizontal = spec.type === 'hbar' || spec.type === 'delta'

    let box = plotBox(height)
    if (horizontal) {
      const firstValues = spec.data
        .map((row) => toNumber(row[spec.series[0].key]))
        .filter((v): v is number => v != null)
      const labelChars = Math.max(0, ...firstValues.map((v) => formatValue(v, fmt).length))
      box = plotBox(height, 132, Math.min(96, Math.max(40, labelChars * 7 + 16)))
    }

    const marks = RENDERERS[spec.type]({ spec, box, min, max, colors, fmt })
    return { colors, height, marks }
  }, [spec])

  const wrapRef = useRef<HTMLDivElement>(null)
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const [dataOpen, setDataOpen] = useState(false)
  const dataId = useId()
  const gradPrefix = `rc${dataId.replace(/:/g, '')}`

  const tipHandlers = (text: string) => ({
    onMouseMove: (e: MouseEvent) => {
      const rect = wrapRef.current?.getBoundingClientRect()
      setTooltip({ text, x: e.clientX - (rect?.left ?? 0), y: e.clientY - (rect?.top ?? 0) })
    },
    onMouseLeave: () => setTooltip(null),
  })

  const showLegend = spec.series.length > 1 && spec.type !== 'delta'

  return (
    <figure ref={wrapRef} className="result-chart" aria-label={`${spec.type} chart: ${spec.title}`}>
      <ChartToolbar spec={spec} dataOpen={dataOpen} dataId={dataId} onToggleData={() => setDataOpen((open) => !open)} />
      {spec.kpis && <KpiTiles kpis={spec.kpis} />}
      <figcaption className="result-chart-head">
        <span className="result-chart-title">{spec.title}</span>
        {spec.subtitle && <span className="result-chart-sub">{spec.subtitle}</span>}
      </figcaption>
      {showLegend && (
        <div className="result-chart-legend">
          {spec.series.map((series, i) => (
            <span key={i}>
              <i style={{ background: layout.colors[i] }} />
              {series.label ?? series.key}
            </span>
          ))}
        </div>
      )}
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${layout.height}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`${spec.type} chart: ${spec.title}`}
        className="result-chart-svg"
      >
        <defs>
          {layout.marks.map((mark, i) =>
            mark.kind === 'path' && mark.variant === 'area' ? (
              <linearGradient key={i} id={`${gradPrefix}-area-${i}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={mark.color} stopOpacity={0.28} />
                <stop offset="100%" stopColor={mark.color} stopOpacity={0} />
              </linearGradient>
            ) : null,
          )}
        </defs>
        {layout.marks.map((mark, i) => renderMark(mark, i, tipHandlers, gradPrefix))}
      </svg>
      {truncation && (
        <p className="result-chart-note">
          Showing top {truncation.shown} of {truncation.total}
        </p>
      )}
      {dataOpen && <ChartDataTable spec={spec} id={dataId} />}
      {tooltip && (
        <div
          role="tooltip"
          className="result-chart-tooltip pointer-events-none absolute z-10"
          style={{ left: tooltip.x, top: tooltip.y, transform: 'translate(-50%, calc(-100% - 12px))' }}
        >
          {tooltip.text}
        </div>
      )}
    </figure>
  )
}

function renderMark(
  mark: Mark,
  key: number,
  tipHandlers: (text: string) => { onMouseMove: (e: MouseEvent) => void; onMouseLeave: () => void },
  gradPrefix: string,
): ReactNode {
  switch (mark.kind) {
    case 'gridline':
      return (
        <line
          key={key}
          x1={mark.x1}
          y1={mark.y1}
          x2={mark.x2}
          y2={mark.y2}
          className="result-chart-gridline"
        />
      )
    case 'rect':
      return (
        <rect
          key={key}
          x={mark.x}
          y={mark.y}
          width={mark.width}
          height={mark.height}
          rx={2}
          fill={mark.color}
          className="result-chart-bar"
          {...tipHandlers(mark.tip)}
        >
          <title>{mark.tip}</title>
        </rect>
      )
    case 'path':
      return mark.variant === 'area' ? (
        <path key={key} d={mark.d} fill={`url(#${gradPrefix}-area-${key})`} className="result-chart-area" />
      ) : (
        <path
          key={key}
          d={mark.d}
          fill="none"
          stroke={mark.color}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          className="result-chart-line"
        />
      )
    case 'dot':
      return (
        <circle
          key={key}
          cx={mark.cx}
          cy={mark.cy}
          r={3}
          fill={mark.color}
          className="result-chart-dot"
          {...tipHandlers(mark.tip)}
        >
          <title>{mark.tip}</title>
        </circle>
      )
    case 'text':
      return (
        <text
          key={key}
          x={mark.x}
          y={mark.y}
          textAnchor={mark.anchor}
          className={`result-chart-${mark.variant === 'value' ? 'vallabel' : mark.variant}`}
        >
          {mark.text}
        </text>
      )
  }
}
