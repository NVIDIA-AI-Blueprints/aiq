// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Logo Component Shim
 *
 * Replaces the internal @kui/foundations-react Logo component which is
 * not available in the public @nvidia/foundations-react-core package.
 * Renders the NVIDIA eye mark as an inline SVG.
 *
 * The fill color is always NVIDIA green (#76b900), hardcoded in the SVG.
 */

import { type FC } from 'react'

interface LogoProps {
  /** 'horizontal' renders a wider logo; 'logo-only' renders the eye mark */
  kind?: 'horizontal' | 'logo-only'
  size?: 'small' | 'medium' | 'large'
  className?: string
}

/** Dimensions when showing the full logo (wider aspect for horizontal layout) */
const fullSizeMap = {
  small: { width: 80, height: 44 },
  medium: { width: 120, height: 66 },
  large: { width: 160, height: 88 },
} as const

/** Dimensions when showing just the eye */
const eyeSizeMap = {
  small: { width: 28, height: 28 },
  medium: { width: 40, height: 40 },
  large: { width: 56, height: 56 },
} as const

/**
 * Renders the NVIDIA logo as an inline SVG.
 *
 * The fill color is always NVIDIA green (#76b900), driven by the
 * CSS variable `--nv-logo-image-color` set on `:root` in globals.css.
 */
export const Logo: FC<LogoProps> = ({ kind = 'horizontal', size = 'medium', className }) => {
  const isEyeOnly = kind === 'logo-only'
  const dims = isEyeOnly ? eyeSizeMap[size] : fullSizeMap[size]

  return (
    <span
      className={className}
      style={{ display: 'inline-flex', alignItems: 'center', width: dims.width, height: dims.height }}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 71 47"
        width={dims.width}
        height={dims.height}
        aria-label="NVIDIA"
        role="img"
      >
        <path
          d="M7.255 20.234s6.419-9.476 19.236-10.455V6.34C12.294 7.481 0 19.51 0 19.51s6.963 20.138 26.491 21.982v-3.655C12.161 36.032 7.255 20.234 7.255 20.234zM26.49 30.57v3.346c-10.83-1.931-13.837-13.194-13.837-13.194s5.2-5.764 13.837-6.698v3.672l-.016-.002c-4.532-.544-8.074 3.692-8.074 3.692s1.984 7.131 8.09 9.184zm0-30.57v6.341c.417-.033.834-.06 1.253-.074 16.14-.544 26.658 13.242 26.658 13.242s-12.08 14.694-24.663 14.694c-1.153 0-2.234-.107-3.248-.287v3.92a21.24 21.24 0 002.704.176c11.71 0 20.18-5.982 28.38-13.063 1.359 1.089 6.925 3.738 8.07 4.9-7.797 6.529-25.968 11.792-36.27 11.792-.993 0-1.947-.06-2.884-.15V47H71V0H26.491zm0 14.024V9.78c.412-.03.829-.052 1.253-.065 11.607-.365 19.222 9.977 19.222 9.977S38.742 31.12 29.923 31.12c-1.27 0-2.407-.205-3.432-.55V17.697c4.52.546 5.428 2.543 8.145 7.073l6.042-5.096s-4.41-5.787-11.845-5.787c-.81 0-1.583.057-2.342.138z"
          fill="#76b900"
        />
      </svg>
    </span>
  )
}
