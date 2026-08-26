// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/adapters/ui'
import { Check, Copy } from '@/adapters/ui/icons'

interface CopyButtonProps {
  text: string
  label?: string
}

const RESET_MS = 1500

/**
 * Tertiary icon button that copies `text` to the clipboard and briefly swaps to a
 * check to confirm. Silently no-ops when the clipboard API is unavailable
 * (e.g. an insecure context) so the answer surface never errors.
 */
export function CopyButton({ text, label = 'Copy' }: CopyButtonProps): ReactNode {
  const [copied, setCopied] = useState(false)
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (resetTimer.current != null) clearTimeout(resetTimer.current)
    },
    [],
  )

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (resetTimer.current != null) clearTimeout(resetTimer.current)
      resetTimer.current = setTimeout(() => setCopied(false), RESET_MS)
    } catch {
      setCopied(false)
    }
  }, [text])

  return (
    <Button
      kind="tertiary"
      size="tiny"
      onClick={handleCopy}
      aria-label={copied ? 'Copied' : label}
      title={copied ? 'Copied' : label}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </Button>
  )
}
