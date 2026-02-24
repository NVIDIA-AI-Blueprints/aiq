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
 * Get auth headers from request, including idToken cookie
 * Returns empty object when REQUIRE_AUTH=false to prevent user identification
 */
const getAuthHeaders = async (req: Request): Promise<Record<string, string>> => {
  // Skip auth when REQUIRE_AUTH=false - don't forward any auth info to backend
  if (!isAuthRequired()) {
    return {}
  }

  const authToken = req.headers.get('Authorization')
  const cookieStore = await cookies()
  const idToken = cookieStore.get('idToken')?.value

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

    console.log('[Deep Research API] GET:', backendUrl, isStreamRequest ? '(SSE)' : '')

    // Get auth headers (includes idToken cookie)
    const authHeaders = await getAuthHeaders(req)
    console.log('[Deep Research API] idToken cookie present:', !!authHeaders.Cookie)

    // Forward the request to the backend
    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        ...authHeaders,
        Accept: isStreamRequest ? 'text/event-stream' : 'application/json',
      },
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
    const authHeaders = await getAuthHeaders(req)
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
