// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Sign In Page
 *
 * Custom sign-in page for OAuth authentication.
 * Redirects to home when REQUIRE_AUTH=false since auth is not needed.
 * Shows DL access denied UI when Helios DL gating is configured and denies the user.
 */

'use client'

import { type ReactNode, Suspense, useEffect } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { signIn } from 'next-auth/react'
import { Flex, Text, Button, Card, Stack, Logo, Spinner } from '@/adapters/ui'
import { LoadingSpinner, Lock } from '@/adapters/ui/icons'
import { useAppConfig } from '@/shared/context'
import { StarfieldAnimation } from '@/shared/components/StarfieldAnimation'

const DISCLAIMER_TEXT =
  'Disclaimer: AI models generate responses and outputs based on complex algorithms and machine learning techniques, and these responses or outputs may be inaccurate, harmful, biased, or indecent. By testing this model, you assume the risk of any harm caused by any response or output of the model. We may capture interaction analytics to improve the application experience. We will not retain your content, documents or output for analysis for training, but may retain it to enable session history. For more information visit the Docs page.'

/**
 * Sign-in form content (uses useSearchParams which requires Suspense)
 */
const SignInContent = (): ReactNode => {
  const router = useRouter()
  const { authRequired, authProviderId } = useAppConfig()
  const searchParams = useSearchParams()
  const error = searchParams?.get('error') ?? null
  const dlGroup = searchParams?.get('dl_group') ?? null
  const isDlDenied = error === 'DLAccessDenied'

  useEffect(() => {
    if (!authRequired) {
      router.replace('/')
    }
  }, [authRequired, router])

  if (!authRequired) {
    return (
      <Flex align="center" justify="center" className="py-8">
        <Spinner size="medium" aria-label="Redirecting..." />
      </Flex>
    )
  }

  const isStarfleet = authProviderId === 'nvlogin'

  const handleSignIn = (): void => {
    signIn(authProviderId, { callbackUrl: '/' })
  }

  const getErrorMessage = (errorCode: string | null): string | null => {
    if (!errorCode) return null

    const errorMessages: Record<string, string> = {
      OAuthSignin:
        'OAuth configuration error. Check that your client ID is set in the environment.',
      OAuthCallback: 'OAuth callback error. The authentication response was invalid.',
      OAuthCreateAccount: 'Could not create user account.',
      EmailCreateAccount: 'Could not create user account.',
      Callback: 'Authentication callback error.',
      OAuthAccountNotLinked: 'This account is linked to a different sign-in method.',
      SessionRequired: 'Please sign in to access this page.',
      Default: 'An authentication error occurred. Please try again.',
    }

    return errorMessages[errorCode] || errorMessages.Default
  }

  const errorMessage = isDlDenied ? null : getErrorMessage(error)
  const buttonLabel = isStarfleet ? 'Sign in with SSO' : 'Sign in'

  return (
    <Stack gap="6" align="center">
      <Logo kind="horizontal" className="h-8" />

      <Flex direction="col" gap="2" align="center">
        <Text kind="title/lg">Sign in to AI-Q</Text>
        <Text kind="body/regular/md" className="text-secondary text-center">
          {isStarfleet ? 'Use your credentials to access AI-Q' : 'Sign in to continue'}
        </Text>
      </Flex>

      {isDlDenied && (
        <Flex
          direction="col"
          gap="3"
          className="bg-status-warning-muted border-status-warning w-full rounded-md border p-4"
        >
          <Flex align="center" gap="density-sm">
            <Lock className="text-status-warning h-5 w-5 shrink-0" />
            <Text kind="label/semibold/sm" className="text-status-warning">
              Access Denied
            </Text>
          </Flex>
          <Text kind="body/regular/sm">
            You are not a member of the required DL group. Please request access, then sign in
            again after approval (may take up to 20 minutes).
          </Text>
          {dlGroup && (
            <Button
              kind="secondary"
              size="small"
              onClick={() =>
                window.open(`https://helios.nvidia.com/dlrequest/group/${dlGroup}`, '_blank')
              }
              aria-label="Request DL access"
            >
              Request Access
            </Button>
          )}
        </Flex>
      )}

      {errorMessage && (
        <Flex
          direction="col"
          gap="2"
          className="bg-status-error-muted border-status-error w-full rounded-md border p-4"
        >
          <Text kind="label/semibold/sm" className="text-status-error">
            Authentication Error
          </Text>
          <Text kind="body/regular/sm">{errorMessage}</Text>
        </Flex>
      )}

      <Button kind="primary" size="large" onClick={handleSignIn} className="w-full">
        {buttonLabel}
      </Button>

      <Text kind="body/regular/sm" className="text-subtle text-center">
        By signing in, you agree to the terms of service and privacy policy.
      </Text>
    </Stack>
  )
}

/**
 * Sign In Page
 */
const SignInPage = (): ReactNode => {
  return (
    <Flex
      direction="col"
      align="center"
      justify="center"
      className="bg-surface-sunken relative min-h-screen p-8"
    >
      {/* Starfield background */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-30">
        <div className="h-[600px] w-[600px]">
          <StarfieldAnimation particleCount={250} maxRadius={250} rotationSpeed={0.001} />
        </div>
      </div>

      {/* Card content */}
      <Card className="relative z-10 w-full max-w-md p-6">
        <Suspense
          fallback={
            <Flex align="center" justify="center" className="py-8">
              <LoadingSpinner size="medium" aria-label="Loading" />
            </Flex>
          }
        >
          <SignInContent />
        </Suspense>
      </Card>

      {/* Disclaimer */}
      <Text
        kind="body/regular/sm"
        className="text-subtle absolute bottom-4 left-1/2 z-10 w-full max-w-3xl -translate-x-1/2 px-4 text-center opacity-70"
      >
        {DISCLAIMER_TEXT}
      </Text>
    </Flex>
  )
}

export default SignInPage
