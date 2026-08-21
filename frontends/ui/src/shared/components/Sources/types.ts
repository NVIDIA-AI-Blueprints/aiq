// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Origin of a cited source. Drives the icon and accent so users can tell
 * document-backed claims from web ones at a glance.
 */
export type SourceKind = 'web' | 'doc'

/**
 * UI-facing representation of a cited source, mapped from the backend's
 * {@link CitationSource}. Kept renderer-agnostic so both inline citation chips
 * and the source-card strip consume the same shape.
 */
export interface SourceRef {
  id: string
  index: number
  title: string
  url?: string
  snippet?: string
  kind: SourceKind
  label: string
}
