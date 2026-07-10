// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type DeepResearchJobLoadFailureKind =
  | 'unavailable'
  | 'backend_unreachable'
  | 'other'

const getErrorText = (error: unknown): string => {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`
  }

  return typeof error === 'string' ? error : ''
}

export const getDeepResearchJobLoadFailureKind = (
  error: unknown
): DeepResearchJobLoadFailureKind => {
  const errorText = getErrorText(error)

  if (/(?:\b(?:404|410)\b|expired|deleted|not found)/i.test(errorText)) {
    return 'unavailable'
  }

  if (
    /(?:PROXY_ERROR|ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|fetch failed|failed to fetch|NetworkError|Load failed)/i.test(
      errorText
    )
  ) {
    return 'backend_unreachable'
  }

  return 'other'
}

export const getDeepResearchJobLoadErrorDetails = (error: unknown): string | undefined => {
  const errorText = getErrorText(error)
  return errorText.replace(/^Error:\s*/, '').trim() || undefined
}

export const isUnavailableDeepResearchJobError = (error: unknown): boolean =>
  getDeepResearchJobLoadFailureKind(error) === 'unavailable'
