// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Auth Error Page
 *
 * Displayed when authentication fails.
 * Redirects to home when REQUIRE_AUTH=false since auth is not needed.
 */

'use client'

import { type ReactNode, Suspense, useEffect } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { Flex, Text, Button, Card, Stack, Spinner } from '@/adapters/ui'
import { useAppConfig } from '@/shared/context'

const errorMessages: Record<string, string> = {
  Configuration: 'There is a problem with the server configuration.',
  AccessDenied: 'You do not have permission to access this resource.',
  Verification: 'The verification link has expired or has already been used.',
  Default: 'An error occurred during authentication.',
}

/**
 * Error content that uses useSearchParams (requires Suspense wrapper)
 */
const ErrorContent = (): ReactNode => {
  const router = useRouter()
  const { authRequired } = useAppConfig()
  const searchParams = useSearchParams()
  const error = searchParams?.get('error') || 'Default'
  const errorMessage = errorMessages[error] || errorMessages.Default

  // Redirect to home if auth is disabled - this page is not needed
  useEffect(() => {
    if (!authRequired) {
      router.replace('/')
    }
  }, [authRequired, router])

  // Show loading while redirecting
  if (!authRequired) {
    return (
      <Flex align="center" justify="center" className="py-8">
        <Spinner size="medium" aria-label="Redirecting..." />
      </Flex>
    )
  }

  const handleRetry = (): void => {
    window.location.href = '/auth/signin'
  }

  const handleHome = (): void => {
    window.location.href = '/'
  }

  return (
    <Stack gap="6" align="center">
      <Flex direction="col" gap="2" align="center">
        <Text kind="title/lg" className="text-feedback-danger">
          Authentication Error
        </Text>
        <Text kind="body/regular/md" className="text-secondary text-center">
          {errorMessage}
        </Text>
      </Flex>

      <Flex gap="3">
        <Button kind="primary" size="medium" onClick={handleRetry}>
          Try Again
        </Button>
        <Button kind="secondary" size="medium" onClick={handleHome}>
          Go Home
        </Button>
      </Flex>
    </Stack>
  )
}

/**
 * Auth Error Page
 */
const AuthErrorPage = (): ReactNode => {
  return (
    <Flex
      direction="col"
      align="center"
      justify="center"
      className="bg-surface-sunken min-h-screen p-8"
    >
      <Card className="w-full max-w-md">
        <Suspense
          fallback={
            <Flex align="center" justify="center" className="py-8">
              <Spinner size="medium" aria-label="Loading" />
            </Flex>
          }
        >
          <ErrorContent />
        </Suspense>
      </Card>
    </Flex>
  )
}

export default AuthErrorPage
