// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export interface StarfieldAnimationProps {
  /** Number of particles to render (default: 350) */
  particleCount?: number
  /** Maximum radius of particle distribution (default: 52) */
  maxRadius?: number
  /** Base size multiplier for particles (default: 1.0) */
  particleSize?: number
  /** Rotation speed in radians per frame (default: 0.002) */
  rotationSpeed?: number
  /** Seed for deterministic random generation (default: 12345) */
  seed?: number
  /** Particle color in RGB format (default: '255, 255, 255') */
  particleColor?: string
  /** Additional CSS classes */
  className?: string
}

export interface Particle {
  angle: number
  radius: number
  size: number
  opacity: number
}
