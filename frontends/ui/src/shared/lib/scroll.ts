// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Distance (px) from the bottom of a scroll container within which the user is
 * still considered "pinned" to the latest content. Small enough that a user who
 * scrolls up to read history is no longer pinned, large enough to tolerate
 * sub-pixel rounding and the growth of a single streaming line.
 */
export const STICK_TO_BOTTOM_THRESHOLD_PX = 120

/**
 * True when a scroll container is within `threshold` px of its bottom.
 *
 * Used to decide whether the chat should auto-follow streaming content: when the
 * user is pinned to the bottom we keep scrolling to the latest token; when they
 * have scrolled up to read earlier messages we leave their position alone.
 *
 * Pure and deterministic so it can be unit-tested without a real layout engine.
 */
export const isPinnedToBottom = (
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  threshold: number = STICK_TO_BOTTOM_THRESHOLD_PX
): boolean => scrollHeight - scrollTop - clientHeight <= threshold
