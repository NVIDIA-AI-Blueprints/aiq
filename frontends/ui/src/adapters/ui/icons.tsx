// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Icon Adapters - CDN SVG Icons
 *
 * Renders NVIDIA brand icons via CDN-hosted SVGs using external-svg-loader.
 * The loader script (in layout.tsx <head>) watches for <svg data-src="...">
 * elements and inlines the fetched SVG content, preserving our attributes.
 *
 * Icons are client-only to avoid hydration mismatches: external-svg-loader
 * mutates the SVG DOM after load (adds viewBox, <symbol>, <use>), which
 * conflicts with React's server-rendered HTML. During SSR an invisible
 * <span> placeholder preserves layout dimensions.
 *
 * CDN naming: icon names use kebab-case WITHOUT category prefix.
 * e.g. npm "CommonMenu" / "ShapesChevronDown" -> CDN "menu" / "chevron-down"
 *
 * Features should import icons from '@/adapters/ui/icons'.
 *
 * @example
 * ```tsx
 * import { ChevronDown, Search, Settings } from '@/adapters/ui/icons'
 *
 * <Button>
 *   <Settings />
 *   Settings
 * </Button>
 * ```
 */

'use client'

import { type FC, useState, useEffect } from 'react'

/** CDN base URL for NVIDIA brand asset icons (pinned version) */
const CDN_VERSION = '3.8.0'
const CDN_BASE = `https://brand-assets.cne.ngc.nvidia.com/assets/icons/${CDN_VERSION}`

// ---------------------------------------------------------------------------
// Base icon props
// ---------------------------------------------------------------------------

interface IconProps {
  className?: string
  width?: number | string
  height?: number | string
  'aria-label'?: string
}

// ---------------------------------------------------------------------------
// Factory: creates a named icon component from a CDN icon name + variant
// ---------------------------------------------------------------------------

const createIcon = (iconName: string, variant: 'line' | 'fill' = 'line'): FC<IconProps> => {
  const Icon: FC<IconProps> = ({ className, width = 20, height = 20, 'aria-label': ariaLabel }) => {
    const [mounted, setMounted] = useState(false)
    useEffect(() => setMounted(true), [])

    // SSR / pre-mount: invisible placeholder preserving layout dimensions
    if (!mounted) {
      return (
        <span
          style={{ display: 'inline-block', width: Number(width), height: Number(height) }}
          aria-hidden="true"
        />
      )
    }

    return (
      <svg
        data-src={`${CDN_BASE}/${variant}/${iconName}.svg`}
        width={width}
        height={height}
        fill="currentColor"
        className={className}
        aria-hidden={!ariaLabel}
        aria-label={ariaLabel}
      />
    )
  }
  Icon.displayName = iconName
  return Icon
}

// ---------------------------------------------------------------------------
// Navigation icons
// CDN names: no category prefix (Shapes* -> just the icon name)
// ---------------------------------------------------------------------------

export const ChevronDown = createIcon('chevron-down')
export const ChevronUp = createIcon('chevron-up')
export const ChevronLeft = createIcon('chevron-left')
export const ChevronRight = createIcon('chevron-right')
export const ArrowLeft = createIcon('arrow-left')
export const ArrowRight = createIcon('arrow-right')
export const Menu = createIcon('menu')

// ---------------------------------------------------------------------------
// Action icons
// CDN names: no category prefix (Common* -> just the icon name)
// ---------------------------------------------------------------------------

export const Search = createIcon('magnifying-glass')
export const Plus = createIcon('add')
export const Minus = createIcon('subtract')
export const Close = createIcon('close')
export const Check = createIcon('check')
export const Edit = createIcon('pencil')
export const Copy = createIcon('copy-generic')
export const Download = createIcon('download')
export const Upload = createIcon('upload')
export const Share = createIcon('share')
export const Refresh = createIcon('refresh')

// ---------------------------------------------------------------------------
// Communication icons
// ---------------------------------------------------------------------------

export const Send = createIcon('forward')
export const Chat = createIcon('chat-single')
export const Mail = createIcon('envelope')

// ---------------------------------------------------------------------------
// Status icons
// ---------------------------------------------------------------------------

export const Info = createIcon('info-circle')
export const Warning = createIcon('warning')
export const Error = createIcon('cancel')
export const Success = createIcon('check')

// ---------------------------------------------------------------------------
// User icons
// ---------------------------------------------------------------------------

export const User = createIcon('profile')
export const Users = createIcon('profile-group')
export const Settings = createIcon('cog')
export const Logout = createIcon('exit')

// ---------------------------------------------------------------------------
// Content icons
// ---------------------------------------------------------------------------

export const Folder = createIcon('folder-closed')
export const Image = createIcon('image')
export const Code = createIcon('code')

// ---------------------------------------------------------------------------
// Theme icons
// ---------------------------------------------------------------------------

export const Sun = createIcon('sun-high')
export const Moon = createIcon('moon')

// ---------------------------------------------------------------------------
// Misc icons
// ---------------------------------------------------------------------------

export const Star = createIcon('star')
export const Heart = createIcon('heart')
export const Home = createIcon('home')
export const Calendar = createIcon('calendar')
export const Clock = createIcon('clock')
export const Filter = createIcon('filter')
export const Sort = createIcon('sort')
export const Wand = createIcon('wand')

// ---------------------------------------------------------------------------
// Aliased / additional icons
// ---------------------------------------------------------------------------

export const Document = createIcon('document')
export const Link = createIcon('link')
export const Trash = createIcon('trash')
export const Globe = createIcon('world')
export const Book = createIcon('book')
export const Help = createIcon('help-circle')
export const Lock = createIcon('lock-closed')
export const Plug = createIcon('plug-recepticle')
export const Wrench = createIcon('wrench')
export const Retry = createIcon('retry')
export const Cancel = createIcon('cancel')

// ---------------------------------------------------------------------------
// GUI icons (previously from @nv-brand-assets/react-icons NvidiaGUIIcon)
// These already used the correct CDN name format
// ---------------------------------------------------------------------------

/** Paperclip icon for file attachment */
export const Paperclip = createIcon('paperclip', 'fill')

/** Paperplane icon for send action */
export const Paperplane = createIcon('paperplane', 'fill')

/** CheckCircle icon for success/complete status */
export const CheckCircle = createIcon('check-circle')

/** ChartFlow icon for workflow/working status */
export const ChartFlow = createIcon('chart-flow')

/** Generate icon for research panel toggle */
export const Generate: FC<IconProps> = ({ className }) => {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  if (!mounted) return <span style={{ display: 'inline-block', width: 24, height: 24 }} aria-hidden="true" />
  return (
    <svg
      data-src={`${CDN_BASE}/line/generate.svg`}
      width="24"
      height="24"
      fill="#76B900"
      className={`nv-icon-green ${className ?? ''}`}
      aria-hidden="true"
    />
  )
}

/** StopCircle icon for stop/cancel actions */
export const StopCircle = createIcon('shape-circle-off')

// ---------------------------------------------------------------------------
// Marketing icons (previously from @nv-brand-assets/react-marketing-icons)
// ---------------------------------------------------------------------------

/** Thinking/Reasoning icon for research panel */
export const ThinkingReasoning = createIcon('neural-network-1')

// ---------------------------------------------------------------------------
// Loading spinner
// ---------------------------------------------------------------------------

interface LoadingSpinnerProps {
  className?: string
  size?: 'small' | 'medium'
  'aria-label'?: string
}

/**
 * Loading spinner using circle-3-q icon with rotation animation.
 * Replaces KUI Spinner for a simpler, branded loading indicator.
 */
export const LoadingSpinner: FC<LoadingSpinnerProps> = ({
  className,
  size = 'small',
  'aria-label': ariaLabel = 'Loading',
}) => {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const sizeClass = size === 'medium' ? 'w-6 h-6' : 'w-4 h-4'
  if (!mounted) {
    return <span className={`${sizeClass} inline-block`} aria-label={ariaLabel} role="status" />
  }
  return (
    <svg
      data-src={`${CDN_BASE}/line/circle-3-q.svg`}
      fill="currentColor"
      className={`animate-spin ${sizeClass} text-brand ${className ?? ''}`}
      aria-label={ariaLabel}
      role="status"
    />
  )
}
