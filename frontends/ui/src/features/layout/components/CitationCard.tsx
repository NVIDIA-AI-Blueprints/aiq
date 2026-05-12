// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * CitationCard Component
 *
 * Non-collapsible card displaying a single citation/source as a clickable link.
 * Shows title/domain and full URL.
 *
 * SSE Events:
 * - artifact.update type: "citation_source" - Referenced (discovered during search)
 * - artifact.update type: "citation_use" - Cited (actually used in report)
 *
 * Verification badge:
 * - `citation_use` events carry a `confidence` (0–1) and `matchKind` from the
 *   backend's source-registry resolver. When `matchKind` is weaker than
 *   exact/normalized we render a small badge so the user can tell strong
 *   matches apart from heuristic ones at a glance.
 */

'use client'

import { type FC } from 'react'
import { Flex, Text } from '@/adapters/ui'
import { Link, Check, Warning, Help } from '@/adapters/ui/icons'
import type { CitationSource, CitationMatchKind } from '@/features/chat/types'

interface CitationCardProps {
  /** Citation information */
  citation: CitationSource
}

/**
 * Format timestamp for display
 */
const formatTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Extract domain from URL for display
 */
const getDomain = (url: string): string => {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname.replace('www.', '')
  } catch {
    return url.substring(0, 30)
  }
}

const MATCH_KIND_LABEL: Record<CitationMatchKind, string> = {
  exact: 'Exact match',
  normalized: 'Matched after normalization (tracking params / fragments)',
  citation_key: 'Document filename matched (page may differ)',
  truncation: 'Matched via truncation — registry URL extends the cited one',
  prefix: 'Prefix match — same scheme/host/path root',
  query_subset: 'Same page, different query parameters',
  child_path: 'Cited URL is a sub-page of a retrieved source',
  ambiguous: 'Multiple registry URLs matched — could not pick one',
  unmatched: 'No matching source in the registry',
  unverifiable: 'Reference text had no recognizable URL or citation key',
}

type BadgeTier = 'high' | 'medium' | 'low' | null

/** Map match_kind to a coarse badge tier. */
const tierForMatchKind = (kind: CitationMatchKind | undefined): BadgeTier => {
  if (!kind) return null
  if (kind === 'exact' || kind === 'normalized') return 'high'
  if (kind === 'truncation' || kind === 'citation_key') return 'medium'
  if (kind === 'prefix' || kind === 'query_subset' || kind === 'child_path') return 'low'
  return null
}

interface ConfidenceBadgeProps {
  matchKind: CitationMatchKind
  confidence: number | undefined
}

/**
 * Small verification badge rendered to the right of the domain. Only shown
 * for non-exact matches — exact matches keep the existing visual unchanged
 * to avoid noise in the common case.
 */
const ConfidenceBadge: FC<ConfidenceBadgeProps> = ({ matchKind, confidence }) => {
  const tier = tierForMatchKind(matchKind)
  if (tier === null || tier === 'high') return null

  const label = MATCH_KIND_LABEL[matchKind]
  const confPct = confidence !== undefined ? ` (${Math.round(confidence * 100)}%)` : ''
  const title = `${label}${confPct}`

  const isMedium = tier === 'medium'
  const Icon = isMedium ? Warning : Help

  return (
    <span
      data-testid="citation-confidence-badge"
      data-match-kind={matchKind}
      data-tier={tier}
      role="img"
      aria-label={title}
      title={title}
      className="shrink-0 inline-flex items-center"
      style={{
        color: isMedium
          ? 'var(--text-color-feedback-warning)'
          : 'var(--text-color-subtle)',
      }}
    >
      <Icon className="h-3.5 w-3.5" />
    </span>
  )
}

/**
 * Non-collapsible card showing a citation source as a clickable link.
 */
export const CitationCard: FC<CitationCardProps> = ({ citation }) => {
  return (
    <a
      href={citation.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block"
    >
      <Flex
        direction="col"
        className="rounded-lg border overflow-hidden bg-surface-sunken border-base hover:bg-surface-raised-50 transition-colors"
      >
        {/* Header */}
        <Flex align="center" gap="2" className="w-full px-3 py-2">
          {/* Status Icon - Cited vs Referenced */}
          <span
            className="shrink-0"
            style={{
              color: citation.isCited
                ? 'var(--text-color-feedback-success)'
                : 'var(--text-color-subtle)',
            }}
            aria-hidden="true"
          >
            {citation.isCited ? (
              <Check className="h-4 w-4" />
            ) : (
              <Link className="h-4 w-4" />
            )}
          </span>

          {/* Citation Title */}
          <Text
            kind="label/semibold/sm"
            className="flex-1 min-w-0 truncate"
            style={{
              color: citation.isCited
                ? 'var(--text-color-feedback-success)'
                : 'var(--text-color-subtle)',
            }}
          >
            {getDomain(citation.url)}
          </Text>

          {/* Confidence badge — only when matchKind exists and isn't exact */}
          {citation.matchKind && (
            <ConfidenceBadge
              matchKind={citation.matchKind}
              confidence={citation.confidence}
            />
          )}

          {/* Timestamp */}
          <Text kind="body/regular/xs" className="text-subtle shrink-0">
            {formatTime(citation.timestamp)}
          </Text>
        </Flex>

        {/* Full URL */}
        <Flex className="px-3 pb-2 border-t border-base">
          <Text kind="body/regular/sm" className="text-subtle truncate mt-1 break-all">
            {citation.url}
          </Text>
        </Flex>
      </Flex>
    </a>
  )
}
