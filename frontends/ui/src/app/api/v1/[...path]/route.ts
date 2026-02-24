// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * V1 API Proxy Route
 *
 * Proxies requests to the backend /v1/* endpoints.
 * Handles collections, documents, data_sources, and other v1 APIs.
 *
 * This allows the frontend to make requests to the same origin,
 * with the backend URL configured at runtime via BACKEND_URL env var.
 *
 * Authentication handling:
 * - When REQUIRE_AUTH=true: Forwards idToken cookie to backend for backend authentication
 * - When REQUIRE_AUTH=false: Skips all auth info to ensure anonymous requests
 */

import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { isAuthRequired } from '@/adapters/auth/config'

const getBackendUrl = (): string => {
  const url = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  return url.replace(/\/$/, '')
}

const buildBackendUrl = (path: string[]): string => {
  const backendBase = getBackendUrl()
  const pathString = path.join('/')
  return `${backendBase}/v1/${pathString}`
}

const getAuthHeaders = async (req: NextRequest): Promise<Record<string, string>> => {
  // Skip auth when REQUIRE_AUTH=false - don't forward any auth info to backend
  if (!isAuthRequired()) {
    return {}
  }

  const authToken = req.headers.get('Authorization')
  const cookieStore = await cookies()
  const idToken = cookieStore.get('idToken')?.value

  return {
    ...(authToken ? { Authorization: authToken } : {}),
    ...(idToken ? { Cookie: `idToken=${idToken}` } : {}),
  }
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  try {
    const { path } = await params
    const backendUrl = buildBackendUrl(path)
    const authHeaders = await getAuthHeaders(req)

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        ...authHeaders,
        Accept: 'application/json',
      },
    })

    if (!response.ok) {
      const errorText = await response.text()
      return new NextResponse(
        JSON.stringify({
          error: { code: 'BACKEND_ERROR', message: `Backend returned ${response.status}: ${errorText}` },
        }),
        { status: response.status, headers: { 'Content-Type': 'application/json' } }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return new NextResponse(
      JSON.stringify({ error: { code: 'PROXY_ERROR', message } }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    )
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  try {
    const { path } = await params
    const backendUrl = buildBackendUrl(path)
    const authHeaders = await getAuthHeaders(req)
    const contentType = req.headers.get('Content-Type') || 'application/json'

    let body: BodyInit | undefined
    const headers: Record<string, string> = { ...authHeaders }

    if (contentType.includes('multipart/form-data')) {
      // Stream the raw body to avoid buffering large uploads in memory
      body = req.body as ReadableStream<Uint8Array>
      headers['Content-Type'] = contentType
    } else {
      headers['Content-Type'] = 'application/json'
      try {
        const json = await req.json()
        body = JSON.stringify(json)
      } catch {
        body = undefined
      }
    }

    const response = await fetch(backendUrl, {
      method: 'POST',
      headers,
      ...(body ? { body, duplex: 'half' } : {}),
    })

    if (!response.ok) {
      const errorText = await response.text()
      return new NextResponse(
        JSON.stringify({
          error: { code: 'BACKEND_ERROR', message: `Backend returned ${response.status}: ${errorText}` },
        }),
        { status: response.status, headers: { 'Content-Type': 'application/json' } }
      )
    }

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return new NextResponse(
      JSON.stringify({ error: { code: 'PROXY_ERROR', message } }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    )
  }
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  try {
    const { path } = await params
    const backendUrl = buildBackendUrl(path)
    const authHeaders = await getAuthHeaders(req)

    let body: string | undefined
    try {
      const json = await req.json()
      body = JSON.stringify(json)
    } catch {
      body = undefined
    }

    const response = await fetch(backendUrl, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
      ...(body ? { body } : {}),
    })

    if (!response.ok) {
      const errorText = await response.text()
      return new NextResponse(
        JSON.stringify({
          error: { code: 'BACKEND_ERROR', message: `Backend returned ${response.status}: ${errorText}` },
        }),
        { status: response.status, headers: { 'Content-Type': 'application/json' } }
      )
    }

    if (response.status === 204) {
      return new NextResponse(null, { status: 204 })
    }

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return new NextResponse(
      JSON.stringify({ error: { code: 'PROXY_ERROR', message } }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    )
  }
}
