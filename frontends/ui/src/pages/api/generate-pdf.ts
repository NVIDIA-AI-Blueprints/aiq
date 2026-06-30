// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { NextApiRequest, NextApiResponse } from 'next'
import React from 'react'
import { renderToStream } from '@react-pdf/renderer'
import { MarkdownPDF } from '../../lib/pdf/ReactPdfDocument'
import { extractArtifactIds, replaceArtifactImages } from '../../shared/components/MarkdownRenderer/artifact-url'
import { isAuthRequired } from '@/adapters/auth/config'

// Cap the bytes we embed per image. Charts are tiny; this guards against base64-inflating a
// large artifact (up to the 50 MB harvest cap) into a pathological PDF.
const MAX_PDF_IMAGE_BYTES = 8 * 1024 * 1024
// Bound the number of artifact fetches per PDF so a report with many refs can't fan out into
// excessive backend load / memory.
const MAX_PDF_ARTIFACT_REFS = 25

const getBackendUrl = (): string => {
  const url = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  return url.replace(/\/$/, '')
}

// This runs server-side and calls the backend directly, so it targets the backend's `/v1`
// route. (The `/api/...` path that the browser uses only exists on the Next.js proxy.)
const backendArtifactContentPath = (jobId: string, artifactId: string): string =>
  `/v1/jobs/async/job/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}/content`

/**
 * Replace every `![alt](artifact://<id>)` with a self-contained `data:` URI by fetching the
 * artifact bytes from the backend. This keeps the PDF fully embedded (no runtime network or
 * auth needed during react-pdf rendering). Refs that fail to resolve are left untouched and
 * the PDF renderer skips them.
 */
const inlineArtifactImages = async (
  markdown: string,
  jobId: string | undefined,
  authHeaders: Record<string, string>
): Promise<string> => {
  if (!jobId) return markdown

  const ids = extractArtifactIds(markdown).slice(0, MAX_PDF_ARTIFACT_REFS)
  console.log(`[PDF] inline: jobId=${jobId} artifactRefs=${ids.length}`)
  if (ids.length === 0) return markdown

  const backend = getBackendUrl()
  const dataUris = new Map<string, string>()
  await Promise.all(
    ids.map(async (id) => {
      try {
        const resp = await fetch(`${backend}${backendArtifactContentPath(jobId, id)}`, {
          headers: { ...authHeaders, Accept: '*/*' },
          // Bound the call so a stalled backend can't hang PDF generation indefinitely.
          signal: AbortSignal.timeout(15_000),
        })
        const contentType = resp.headers.get('Content-Type') ?? 'application/octet-stream'
        console.log(`[PDF] fetch ${id}: status=${resp.status} type=${contentType}`)
        if (!resp.ok) return
        // Only raster images are embeddable in the PDF.
        if (!contentType.startsWith('image/')) return
        // Reject oversized artifacts by declared length before buffering the whole body.
        const declaredLen = Number(resp.headers.get('Content-Length'))
        if (Number.isFinite(declaredLen) && declaredLen > MAX_PDF_IMAGE_BYTES) {
          console.warn(`[PDF] Skipping artifact ${id}: declared ${declaredLen} bytes exceeds embed cap`)
          return
        }
        const buffer = Buffer.from(await resp.arrayBuffer())
        if (buffer.byteLength > MAX_PDF_IMAGE_BYTES) {
          console.warn(`[PDF] Skipping artifact ${id}: ${buffer.byteLength} bytes exceeds embed cap`)
          return
        }
        dataUris.set(id, `data:${contentType};base64,${buffer.toString('base64')}`)
      } catch (err) {
        console.error('[PDF] Failed to fetch artifact', id, err)
      }
    })
  )

  console.log(`[PDF] inline: embedded ${dataUris.size}/${ids.length} image(s) as data URIs`)
  return replaceArtifactImages(markdown, (alt, id) => {
    const uri = dataUris.get(id)
    return uri ? `![${alt}](${uri})` : null
  })
}

/**
 * POST /api/generate-pdf
 * Receives: { markdown: string, jobId?: string } in JSON body
 * Returns: PDF file generated from markdown as application/pdf
 */
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { markdown, jobId } = req.body

    if (!markdown || typeof markdown !== 'string') {
      return res.status(400).json({ error: 'Invalid or missing markdown content' })
    }

    // Forward only the auth the artifact endpoint needs — the Authorization header and the
    // idToken cookie — rather than the caller's entire cookie jar. Gated on isAuthRequired()
    // so anonymous mode (REQUIRE_AUTH=false) sends no identity headers, matching the jobs proxy.
    const authHeaders: Record<string, string> = {}
    if (isAuthRequired()) {
      if (req.headers.authorization) authHeaders.Authorization = req.headers.authorization
      const idTokenCookie = req.headers.cookie
        ?.split(';')
        .map((c) => c.trim())
        .find((c) => c.startsWith('idToken='))
      if (idTokenCookie) authHeaders.Cookie = idTokenCookie
    }

    const resolvedMarkdown = await inlineArtifactImages(
      markdown,
      typeof jobId === 'string' ? jobId : undefined,
      authHeaders
    )

    const stream = await renderToStream(
      React.createElement(MarkdownPDF, { markdown: resolvedMarkdown }) as React.ReactElement
    )

    const chunks: Buffer[] = []
    for await (const chunk of stream) {
      chunks.push(Buffer.from(chunk))
    }

    const pdfBuffer = Buffer.concat(chunks)

    res.setHeader('Content-Type', 'application/pdf')
    res.setHeader('Content-Disposition', 'attachment; filename="report.pdf"')
    res.send(pdfBuffer)
  } catch (error) {
    console.error('[PDF] Error generating PDF:', error)
    res.status(500).json({
      error: 'Failed to generate PDF',
      details: error instanceof Error ? error.message : 'Unknown error',
    })
  }
}
