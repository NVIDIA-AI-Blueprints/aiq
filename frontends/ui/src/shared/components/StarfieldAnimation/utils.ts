// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Seedable pseudo-random number generator using sine-based algorithm.
 * Provides deterministic random values for consistent particle placement.
 */
export class SeededRandom {
  private seed: number

  constructor(seed: number) {
    this.seed = seed
  }

  /** Returns a pseudo-random number between 0 and 1 */
  next(): number {
    const x = Math.sin(this.seed++) * 10000
    return x - Math.floor(x)
  }

  /** Resets the generator to the initial seed */
  reset(seed: number): void {
    this.seed = seed
  }
}
