// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { SupportedLanguage } from './types'

const LANGUAGE_MAP: Record<string, SupportedLanguage> = {
  ts: 'typescript',
  typescript: 'typescript',
  js: 'javascript',
  javascript: 'javascript',
  tsx: 'tsx',
  jsx: 'jsx',
  py: 'python',
  python: 'python',
  json: 'json',
  bash: 'bash',
  sh: 'shell',
  shell: 'shell',
  html: 'html',
  css: 'css',
  yaml: 'yaml',
  yml: 'yaml',
  md: 'markdown',
  markdown: 'markdown',
  go: 'go',
  golang: 'go',
  rust: 'rust',
  rs: 'rust',
}

/**
 * Extract language from markdown code fence className
 * e.g., "language-typescript" -> "typescript"
 */
export const getLanguageFromClassName = (className?: string): SupportedLanguage => {
  if (!className) return 'bash' // Default fallback for unlabeled code blocks

  const match = className.match(/language-(\w+)/)
  if (!match) return 'bash'

  const lang = match[1].toLowerCase()
  return LANGUAGE_MAP[lang] || 'bash'
}
