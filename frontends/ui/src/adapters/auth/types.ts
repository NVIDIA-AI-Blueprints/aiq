// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * NextAuth Type Extensions
 *
 * Extends the default NextAuth types to include custom session properties
 * for OAuth authentication.
 */

import 'next-auth'
import 'next-auth/jwt'

declare module 'next-auth' {
  /**
   * Extended Session interface with OAuth tokens
   */
  interface Session {
    /** The OAuth access token */
    accessToken?: string
    /** The OIDC ID token (used for backend auth) */
    idToken?: string
    /** User ID from the OAuth provider */
    userId?: string
    /** Error state for token refresh failures */
    error?: string
  }

  /**
   * Extended User interface
   */
  interface User {
    id: string
    email?: string | null
    name?: string | null
    image?: string | null
  }
}

declare module 'next-auth/jwt' {
  /**
   * Extended JWT interface with OAuth tokens
   */
  interface JWT {
    /** The OAuth access token */
    accessToken?: string
    /** The OIDC ID token */
    idToken?: string
    /** The OAuth refresh token */
    refreshToken?: string
    /** Token expiration timestamp (seconds since epoch) */
    expiresAt?: number
    /** User ID from the OAuth provider */
    userId?: string
    /** Error state for token refresh failures */
    error?: string
  }
}

/**
 * Auth state for the useAuth hook
 */
export interface AuthState {
  /** Whether the user is authenticated */
  isAuthenticated: boolean
  /** Whether the auth state is loading */
  isLoading: boolean
  /** Whether authentication is required via REQUIRE_AUTH env var */
  authRequired: boolean
  /** The authenticated user */
  user: {
    id?: string
    email?: string | null
    name?: string | null
    image?: string | null
  } | null
  /** The access token for API calls */
  accessToken?: string
  /** The ID token for backend auth */
  idToken?: string
  /** Any auth error */
  error?: string
}

/**
 * Auth actions for the useAuth hook
 */
export interface AuthActions {
  /** Sign in with OAuth */
  signIn: () => Promise<void>
  /** Sign out and clear session */
  signOut: () => Promise<void>
}

/**
 * Complete auth context type
 */
export type AuthContext = AuthState & AuthActions
