// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const DEFAULT_FILENAME = 'report'
const MAX_LENGTH = 100

/**
 * Strips characters that are invalid in filenames across OS platforms,
 * collapses whitespace into hyphens, and truncates to a safe length.
 * Returns a fallback name when the result would be empty.
 */
export function sanitizeFilename(title: string): string {
  return (
    title
      .replace(/[/\\:*?"<>|]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
      .toLowerCase()
      .slice(0, MAX_LENGTH) || DEFAULT_FILENAME
  )
}
