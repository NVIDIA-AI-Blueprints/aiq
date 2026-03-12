// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { type ReactNode } from 'react'
import {
  Svg,
  G,
  Path,
  Rect,
  Circle,
  Ellipse,
  Line,
  Polygon,
  Polyline,
  Text as PdfText,
  View,
} from '@react-pdf/renderer'
import { parse, type SvgElementNode, type SvgNode, type SvgTextNode } from 'svg-parser'
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js'
import { SVG } from 'mathjax-full/js/output/svg.js'
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'

const EX_TO_PT = 4.3
const PX_TO_PT = 0.75
const renderCache = new Map<string, string>()

const adaptor = liteAdaptor()
RegisterHTMLHandler(adaptor)

const tex = new TeX({ packages: AllPackages })
const svg = new SVG({ fontCache: 'none' })
const html = mathjax.document('', {
  InputJax: tex,
  OutputJax: svg,
})

interface MathSvgProps {
  latex: string
  display?: boolean
  fontSize?: number
}

interface PdfSvgAttributes {
  [key: string]: string | number | undefined
}

function renderMathToSvgMarkup(latex: string, display: boolean): string {
  const cacheKey = `${display ? 'display' : 'inline'}:${latex}`
  const cached = renderCache.get(cacheKey)

  if (cached) {
    return cached
  }

  const node = html.convert(latex, { display })
  const markup = adaptor.outerHTML(node)
  renderCache.set(cacheKey, markup)

  return markup
}

function extractSvgNode(markup: string): SvgElementNode | null {
  const root = parse(markup)
  const stack: SvgNode[] = [...root.children]

  while (stack.length > 0) {
    const current = stack.shift()

    if (!current || current.type !== 'element') {
      continue
    }

    if (current.tagName === 'svg') {
      return current
    }

    stack.unshift(...current.children)
  }

  return null
}

function toPoints(value: string | undefined, fontSize: number): number | undefined {
  if (!value) return undefined

  const trimmed = value.trim()
  if (!trimmed) return undefined

  const numericValue = Number.parseFloat(trimmed)
  if (Number.isNaN(numericValue)) return undefined

  if (trimmed.endsWith('ex')) return numericValue * EX_TO_PT
  if (trimmed.endsWith('em')) return numericValue * fontSize
  if (trimmed.endsWith('px')) return numericValue * PX_TO_PT

  return numericValue
}

function toCamelCase(value: string): string {
  return value.replace(/-([a-z])/g, (_, char: string) => char.toUpperCase())
}

function parseStyleAttribute(style: string): Record<string, string> {
  return style
    .split(';')
    .map((entry) => entry.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, entry) => {
      const [name, ...rest] = entry.split(':')
      if (!name || rest.length === 0) return acc

      acc[toCamelCase(name.trim())] = rest.join(':').trim()
      return acc
    }, {})
}

function getPdfSvgAttributes(node: SvgElementNode): PdfSvgAttributes {
  const attributes: PdfSvgAttributes = {}
  const entries = Object.entries(node.properties)

  for (const [rawName, rawValue] of entries) {
    if (rawValue == null) continue
    if (
      rawName === 'xmlns' ||
      rawName === 'role' ||
      rawName === 'focusable' ||
      rawName === 'class' ||
      rawName.startsWith('data-')
    ) {
      continue
    }

    if (rawName === 'style') {
      Object.assign(attributes, parseStyleAttribute(rawValue))
      continue
    }

    const name = rawName === 'stroke-width' ? 'strokeWidth' : toCamelCase(rawName)
    attributes[name] = rawValue
  }

  if (attributes.fill === 'currentColor') {
    attributes.fill = '#111111'
  }

  if (attributes.stroke === 'currentColor') {
    attributes.stroke = '#111111'
  }

  return attributes
}

function renderSvgChild(node: SvgElementNode | SvgTextNode, key: string): ReactNode {
  if (node.type === 'text') {
    const text = node.value.trim()
    return text ? <PdfText key={key}>{text}</PdfText> : null
  }

  const attributes = getPdfSvgAttributes(node)
  const children = node.children.map((child, index) => renderSvgChild(child, `${key}-${index}`))

  switch (node.tagName) {
    case 'g':
      return (
        <G key={key} {...attributes}>
          {children}
        </G>
      )
    case 'path':
      return <Path key={key} d={String(attributes.d ?? '')} {...attributes} />
    case 'rect':
      return (
        <Rect
          key={key}
          width={String(attributes.width ?? 0)}
          height={String(attributes.height ?? 0)}
          x={attributes.x}
          y={attributes.y}
          rx={attributes.rx}
          ry={attributes.ry}
          {...attributes}
        />
      )
    case 'circle':
      return <Circle key={key} r={String(attributes.r ?? 0)} cx={attributes.cx} cy={attributes.cy} {...attributes} />
    case 'ellipse':
      return (
        <Ellipse
          key={key}
          rx={String(attributes.rx ?? 0)}
          ry={String(attributes.ry ?? 0)}
          cx={attributes.cx}
          cy={attributes.cy}
          {...attributes}
        />
      )
    case 'line':
      return (
        <Line
          key={key}
          x1={String(attributes.x1 ?? 0)}
          y1={String(attributes.y1 ?? 0)}
          x2={String(attributes.x2 ?? 0)}
          y2={String(attributes.y2 ?? 0)}
          {...attributes}
        />
      )
    case 'polygon':
      return <Polygon key={key} points={String(attributes.points ?? '')} {...attributes} />
    case 'polyline':
      return <Polyline key={key} points={String(attributes.points ?? '')} {...attributes} />
    default:
      return null
  }
}

export const MathSvg: React.FC<MathSvgProps> = ({ latex, display = false, fontSize = 10 }) => {
  try {
    const svgMarkup = renderMathToSvgMarkup(latex, display)
    const svgNode = extractSvgNode(svgMarkup)

    if (!svgNode) {
      return <PdfText>{latex}</PdfText>
    }

    const width = toPoints(svgNode.properties.width, fontSize)
    const height = toPoints(svgNode.properties.height, fontSize)
    const inlineStyle = getPdfSvgAttributes(svgNode).verticalAlign
    const verticalAlign = typeof inlineStyle === 'string' ? toPoints(inlineStyle, fontSize) ?? 0 : 0
    const children = svgNode.children.map((child, index) => renderSvgChild(child, `svg-${index}`))

    return (
      <View
        style={
          display
            ? { alignItems: 'center', marginTop: 8, marginBottom: 10 }
            : { marginLeft: 1, marginRight: 1, marginBottom: verticalAlign }
        }
      >
        <Svg
          width={width ?? fontSize * 2}
          height={height ?? fontSize}
          viewBox={svgNode.properties.viewBox}
          preserveAspectRatio={svgNode.properties.preserveAspectRatio}
        >
          {children}
        </Svg>
      </View>
    )
  } catch {
    return <PdfText>{latex}</PdfText>
  }
}
