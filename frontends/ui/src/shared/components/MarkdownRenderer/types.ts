// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export interface MarkdownRendererProps {
  /** Markdown content to render */
  content: string
  /** Whether content is still streaming (affects rendering optimization) */
  isStreaming?: boolean
  /** Additional CSS classes for the wrapper */
  className?: string
  /** Use compact text sizes (for chat bubbles vs full reports) */
  compact?: boolean
  /**
   * Owning job id used to resolve `artifact://<id>` image refs to the content endpoint.
   * When omitted, artifact images are not resolved (rendered as-is).
   */
  artifactJobId?: string
}

/** Supported languages for syntax highlighting */
export type SupportedLanguage =
  | 'typescript'
  | 'javascript'
  | 'tsx'
  | 'jsx'
  | 'python'
  | 'json'
  | 'bash'
  | 'shell'
  | 'html'
  | 'css'
  | 'yaml'
  | 'markdown'
  | 'go'
  | 'rust'
