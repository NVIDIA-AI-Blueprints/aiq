// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import {
  type FC,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'

interface MermaidBlockProps {
  code: string
  fallback: ReactNode
}

const MIN_SCALE = 0.25
const MAX_SCALE = 5
const ZOOM_STEP = 0.25

const clamp = (v: number): number => Math.min(MAX_SCALE, Math.max(MIN_SCALE, v))

const isDarkTheme = (): boolean =>
  typeof document !== 'undefined' && document.documentElement.classList.contains('nv-dark')

/**
 * Renders a fenced ```mermaid block (e.g. the schema ER diagram) as an SVG diagram in the chat.
 *
 * Mermaid is heavy and DOM-bound, so it is dynamically imported on the client and only when a diagram is
 * actually present. Wide schemas with many tables are unreadable when squeezed to the container width, so the
 * diagram opens fit-to-width and is then zoomable (buttons, wheel-to-cursor) and pan-able (drag / scroll). The
 * theme tracks the app's light/dark mode, and any parse or render failure falls back to the raw code block.
 */
export const MermaidBlock: FC<MermaidBlockProps> = ({ code, fallback }) => {
  const renderId = `mermaid-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const [svg, setSvg] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [dark, setDark] = useState(isDarkTheme)

  const [base, setBase] = useState<{ w: number; h: number } | null>(null)
  const [scale, setScale] = useState(1)
  const [fullscreen, setFullscreen] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const anchorRef = useRef<{ ratio: number; contentX: number; contentY: number; cx: number; cy: number } | null>(null)
  const scaleRef = useRef(scale)
  scaleRef.current = scale

  useEffect(() => {
    const observer = new MutationObserver(() => setDark(isDarkTheme()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let active = true
    setFailed(false)

    void (async () => {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: dark ? 'dark' : 'default',
          er: { useMaxWidth: true },
          themeVariables: { fontFamily: 'ui-sans-serif, system-ui, sans-serif' },
        })
        const result = await mermaid.render(renderId, code)
        if (active) setSvg(result.svg)
      } catch {
        if (active) {
          setSvg(null)
          setFailed(true)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [code, dark, renderId])

  useEffect(() => {
    if (!svg) {
      setBase(null)
      return
    }
    const m = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/)
    setBase(m ? { w: parseFloat(m[1]), h: parseFloat(m[2]) } : null)
  }, [svg])

  const fit = useCallback(() => {
    const el = scrollRef.current
    if (!el || !base) return
    const avail = el.clientWidth - 32
    if (avail > 0) setScale(clamp(avail / base.w))
  }, [base])

  useEffect(() => {
    fit()
  }, [fit])

  useEffect(() => {
    fit()
  }, [fullscreen, fit])

  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  useEffect(() => {
    if (fullscreen) {
      triggerRef.current = document.activeElement as HTMLElement | null
      dialogRef.current?.focus()
      return
    }
    const trigger = triggerRef.current
    if (trigger) {
      trigger.focus()
      triggerRef.current = null
    }
  }, [fullscreen])

  useLayoutEffect(() => {
    const a = anchorRef.current
    const el = scrollRef.current
    if (!a || !el) return
    el.scrollLeft = a.contentX * a.ratio - a.cx
    el.scrollTop = a.contentY * a.ratio - a.cy
    anchorRef.current = null
  }, [scale])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !base) return
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const cx = e.clientX - rect.left
      const cy = e.clientY - rect.top
      const prev = scaleRef.current
      const next = clamp(prev * Math.exp(-e.deltaY * 0.0015))
      if (next === prev) return
      anchorRef.current = { ratio: next / prev, contentX: el.scrollLeft + cx, contentY: el.scrollTop + cy, cx, cy }
      setScale(next)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [base])

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (!base || e.button !== 0) return
    const el = scrollRef.current
    if (!el) return
    dragRef.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop }
    el.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = dragRef.current
    const el = scrollRef.current
    if (!d || !el) return
    el.scrollLeft = d.left - (e.clientX - d.x)
    el.scrollTop = d.top - (e.clientY - d.y)
  }
  const endDrag = (): void => {
    dragRef.current = null
  }

  if (failed) return <>{fallback}</>

  if (!svg) {
    return (
      <div
        className="border-base bg-surface-raised text-secondary my-3 grid h-32 place-items-center rounded-[var(--radius-card)] border text-sm"
        aria-busy="true"
      >
        Rendering diagram…
      </div>
    )
  }

  const zoomable = base !== null

  return (
    <div
      ref={dialogRef}
      role={fullscreen ? 'dialog' : undefined}
      aria-modal={fullscreen ? true : undefined}
      aria-label={fullscreen ? 'Diagram fullscreen view' : undefined}
      tabIndex={fullscreen ? -1 : undefined}
      className={
        fullscreen
          ? 'bg-surface-raised fixed inset-0 z-[60] m-0 overflow-hidden border-0'
          : 'border-base bg-surface-raised relative my-3 overflow-hidden rounded-[var(--radius-card)] border'
      }
    >
      {zoomable && (
        <div className="absolute right-2 top-2 z-10 flex items-center gap-0.5 rounded-full border border-[color:var(--border-color-base)] bg-[color:var(--background-color-surface-raised)]/90 px-1 py-0.5 backdrop-blur">
          <button
            type="button"
            aria-label="Zoom out"
            onClick={() => setScale((s) => clamp(s - ZOOM_STEP))}
            className="text-secondary grid h-6 w-6 place-items-center rounded-full text-base leading-none hover:bg-[color:color-mix(in_srgb,var(--text-color-primary)_8%,transparent)]"
          >
            −
          </button>
          <button
            type="button"
            aria-label="Reset zoom"
            onClick={fit}
            className="text-subtle min-w-[2.75rem] px-1 text-center text-[0.7rem] tabular-nums hover:text-[color:var(--text-color-secondary)]"
          >
            {Math.round(scale * 100)}%
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            onClick={() => setScale((s) => clamp(s + ZOOM_STEP))}
            className="text-secondary grid h-6 w-6 place-items-center rounded-full text-base leading-none hover:bg-[color:color-mix(in_srgb,var(--text-color-primary)_8%,transparent)]"
          >
            +
          </button>
          <button
            type="button"
            aria-label={fullscreen ? 'Exit fullscreen' : 'Expand to fullscreen'}
            title={fullscreen ? 'Exit fullscreen (Esc)' : 'Expand to fullscreen'}
            onClick={() => setFullscreen((f) => !f)}
            className="text-secondary grid h-6 w-6 place-items-center rounded-full text-base leading-none hover:bg-[color:color-mix(in_srgb,var(--text-color-primary)_8%,transparent)]"
          >
            {fullscreen ? '×' : '⤢'}
          </button>
        </div>
      )}
      <div
        ref={scrollRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className={
          [
            fullscreen ? 'h-screen max-h-screen' : 'max-h-[70vh]',
            zoomable
              ? 'cursor-grab touch-none select-none overflow-auto p-4 active:cursor-grabbing'
              : 'overflow-auto p-4',
          ].join(' ')
        }
      >
        <div
          role="img"
          aria-label="Diagram"
          style={zoomable ? { width: base.w * scale, height: base.h * scale } : undefined}
          className={
            zoomable
              ? '[&_svg]:!h-full [&_svg]:!w-full [&_svg]:!max-w-none'
              : '[&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full'
          }
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  )
}
