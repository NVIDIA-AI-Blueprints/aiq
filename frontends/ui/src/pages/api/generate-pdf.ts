// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { NextApiRequest, NextApiResponse } from 'next'
import React from 'react'
import { renderToStream } from '@react-pdf/renderer'
import { MarkdownPDF } from '../../lib/pdf/ReactPdfDocument'

/**
 * POST /api/generate-pdf
 * Receives: { markdown: string } in JSON body
 * Returns: PDF file generated from markdown as application/pdf
 */
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { markdown } = req.body

    if (!markdown || typeof markdown !== 'string') {
      return res.status(400).json({ error: 'Invalid or missing markdown content' })
    }

    const stream = await renderToStream(
      React.createElement(MarkdownPDF, { markdown }) as React.ReactElement
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
