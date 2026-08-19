// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tokens that render fully upper-cased in humanized names (e.g. tool / function
 * labels) rather than title-cased, so `api_gateway` becomes "API Gateway", not
 * "Api Gateway".
 */
export const ACRONYMS = new Set(['ai', 'api', 'sql', 'gpt', 'llm', 'url', 'pdf', 'csv', 'json'])

/**
 * Humanize a snake_case / `__`-separated identifier into a display label,
 * upper-casing known acronyms. Collapses runs of separators (so
 * `web_search_tool` -> "Web Search Tool", `api__gateway` -> "API Gateway").
 */
export function titleCaseWords(text: string): string {
  return text
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) =>
      ACRONYMS.has(word.toLowerCase())
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
    )
    .join(' ')
}
