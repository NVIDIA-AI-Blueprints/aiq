// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Deep Research API Route Proxy
 *
 * Proxies requests to the deep research async jobs API.
 * This avoids CORS issues by keeping browser requests on the same origin.
 *
 * Authentication handling:
 * - When REQUIRE_AUTH=true: Forwards idToken cookie to backend for backend authentication
 * - When REQUIRE_AUTH=false: Skips all auth info to ensure anonymous requests
 *
 * Handles:
 * - GET /api/jobs/async/agents - List available agents
 * - POST /api/jobs/async/submit - Submit a new job
 * - GET /api/jobs/async/job/{job_id} - Get job status
 * - GET /api/jobs/async/job/{job_id}/stream - SSE stream (primary use case)
 * - GET /api/jobs/async/job/{job_id}/stream/{last_event_id} - SSE reconnection
 * - POST /api/jobs/async/job/{job_id}/cancel - Cancel job
 * - GET /api/jobs/async/job/{job_id}/state - Get job artifacts
 * - GET /api/jobs/async/job/{job_id}/report - Get final report
 *
 * @see docs/api.md - Deep Research API section
 */

import { NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { isAuthRequired } from '@/adapters/auth/config'

const getBackendUrl = (): string => {
  const url = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  return url.replace(/\/$/, '')
}

/**
 * Build the backend URL for deep research API
 */
const buildBackendUrl = (path: string[]): string => {
  const backendBase = getBackendUrl()
  const pathString = path.join('/')
  return `${backendBase}/v1/jobs/async/${pathString}`
}

/**
 * Get auth headers from request, including idToken cookie.
 * Returns empty object when REQUIRE_AUTH=false to prevent user identification.
 *
 * For SSE stream paths, accepts a ?token= query parameter as a fallback
 * because EventSource cannot set custom headers or cookies.
 */
const getAuthHeaders = async (req: Request, pathSegments: string[]): Promise<Record<string, string>> => {
  // Skip auth when REQUIRE_AUTH=false - don't forward any auth info to backend
  if (!isAuthRequired()) {
    return {}
  }

  // Only allow query token for stream paths (EventSource can't set headers).
  // Note: tokens in URLs may appear in server access logs. This is a
  // server-side route handler — the token is extracted here and forwarded
  // only via headers, never passed on as a URL to the backend.
  const allowQueryToken = pathSegments.includes('stream')
  const rawQueryToken = new URL(req.url).searchParams.get('token')?.trim()
  const queryToken = allowQueryToken && rawQueryToken ? rawQueryToken : undefined
  const cookieStore = await cookies()
  const cookieIdToken = cookieStore.get('idToken')?.value?.trim()
  const idToken = cookieIdToken || queryToken
  const authToken = req.headers.get('Authorization') || (idToken ? `Bearer ${idToken}` : null)

  if (queryToken && !cookieIdToken) {
    console.warn('[Deep Research API] SSE stream using ?token= query fallback (idToken cookie missing)')
  }

  return {
    ...(authToken ? { Authorization: authToken } : {}),
    // Forward the idToken cookie to the backend
    ...(idToken ? { Cookie: `idToken=${idToken}` } : {}),
  }
}

/**
 * Handle GET requests (status, stream, state, report)
 */
export async function GET(
  req: Request,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  try {
    const { path } = await params
    const backendUrl = buildBackendUrl(path)
    const isStreamRequest = path.includes('stream')
    // Artifact bytes (.../artifacts/{id}/content) are binary — never JSON-parse them.
    const isArtifactContent = path.includes('artifacts') && path[path.length - 1] === 'content'

    console.log('[Deep Research API] GET:', backendUrl, isStreamRequest ? '(SSE)' : '')

    // Get auth headers (includes idToken cookie)
    const authHeaders = await getAuthHeaders(req, path)
    console.log('[Deep Research API] idToken cookie present:', !!authHeaders.Cookie)

    // Forward the request to the backend
    const acceptHeader = isStreamRequest
      ? 'text/event-stream'
      : isArtifactContent
        ? '*/*'
        : 'application/json'
    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        ...authHeaders,
        Accept: acceptHeader,
      },
      ...(isStreamRequest ? { signal: req.signal } : {}),
    })

    // Handle error responses
    if (!response.ok) {
      const errorText = await response.text()
      console.error('[Deep Research API] Backend error:', response.status, errorText)

      return new NextResponse(
        JSON.stringify({
          error: {
            code: 'BACKEND_ERROR',
            message: `Backend returned ${response.status}: ${errorText}`,
          },
        }),
        {
          status: response.status,
          headers: { 'Content-Type': 'application/json' },
        }
      )
    }

    // For SSE streams, pass through the response body
    if (isStreamRequest) {
      if (!response.body) {
        return new NextResponse(
          JSON.stringify({
            error: {
              code: 'NO_RESPONSE_BODY',
              message: 'Backend returned no SSE stream body',
            },
          }),
          {
            status: 500,
            headers: { 'Content-Type': 'application/json' },
          }
        )
      }

      // Stream the SSE response back to the client
      return new NextResponse(response.body, {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache, no-transform',
          Connection: 'keep-alive',
          'X-Accel-Buffering': 'no', // Disable nginx buffering
        },
      })
    }

    // For artifact content, stream the raw bytes through with the upstream content type
    // (JSON-parsing here would corrupt binary payloads like PNGs).
    if (isArtifactContent) {
      if (!response.body) {
        return new NextResponse(
          JSON.stringify({
            error: { code: 'NO_RESPONSE_BODY', message: 'Backend returned no artifact content' },
          }),
          { status: 502, headers: { 'Content-Type': 'application/json' } }
        )
      }
      const passthroughHeaders: Record<string, string> = {
        'Content-Type': response.headers.get('Content-Type') ?? 'application/octet-stream',
        'Cache-Control': 'private, max-age=3600',
      }
      const disposition = response.headers.get('Content-Disposition')
      if (disposition) passthroughHeaders['Content-Disposition'] = disposition
      return new NextResponse(response.body, { status: response.status, headers: passthroughHeaders })
    }

    // For regular JSON responses
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('[Deep Research API] GET error:', error)

    const errorMessage = error instanceof Error ? error.message : 'Unknown error'

    return new NextResponse(
      JSON.stringify({
        error: {
          code: 'PROXY_ERROR',
          message: errorMessage,
        },
      }),
      {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }
    )
  }
}

/**
 * Handle POST requests (submit, cancel)
 */
export async function POST(
  req: Request,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  try {
    const { path } = await params
    const backendUrl = buildBackendUrl(path)

    console.log('[Deep Research API] POST:', backendUrl)

    // Get the request body (may be empty for cancel)
    let body: string | undefined
    try {
      const json = await req.json()
      body = JSON.stringify(json)
    } catch {
      // No body or invalid JSON - that's okay for cancel
      body = undefined
    }

    // Get auth headers (includes idToken cookie)
    const authHeaders = await getAuthHeaders(req, path)
    console.log('[Deep Research API] POST idToken cookie present:', !!authHeaders.Cookie)

    // Forward the request to the backend
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
      ...(body ? { body } : {}),
    })

    // Handle error responses
    if (!response.ok) {
      const errorText = await response.text()
      console.error('[Deep Research API] Backend error:', response.status, errorText)

      return new NextResponse(
        JSON.stringify({
          error: {
            code: 'BACKEND_ERROR',
            message: `Backend returned ${response.status}: ${errorText}`,
          },
        }),
        {
          status: response.status,
          headers: { 'Content-Type': 'application/json' },
        }
      )
    }

    // Return JSON response
    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('[Deep Research API] POST error:', error)

    const errorMessage = error instanceof Error ? error.message : 'Unknown error'

    return new NextResponse(
      JSON.stringify({
        error: {
          code: 'PROXY_ERROR',
          message: errorMessage,
        },
      }),
      {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }
    )
  }
}
