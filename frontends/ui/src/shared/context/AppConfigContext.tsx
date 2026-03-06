// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * App Configuration Context
 *
 * Provides runtime configuration values from server-side environment variables.
 * This allows configuration to be changed at runtime without rebuilding.
 *
 * Values are passed from server components (layout.tsx) to client components
 * via this context, avoiding the need for NEXT_PUBLIC_ prefixed variables.
 */

'use client'

import { createContext, useContext, type ReactNode } from 'react'

/**
 * File upload configuration for validation limits
 */
export interface FileUploadConfig {
  /** Accepted file extensions (e.g., ".pdf,.docx,.txt,.md") */
  acceptedTypes: string
  /** Accepted MIME types for drag-drop validation */
  acceptedMimeTypes: string[]
  /** Maximum total size in MB */
  maxTotalSizeMB: number
  /** Maximum file size in bytes (derived from maxTotalSizeMB) */
  maxFileSize: number
  /** Maximum total size in bytes (derived from maxTotalSizeMB) */
  maxTotalSize: number
  /** Maximum number of files per session */
  maxFileCount: number
  /** Hours after upload before files may expire on the backend (0 = no expiry shown) */
  fileExpirationCheckIntervalHours: number
}

/**
 * Runtime configuration passed from server to client
 */
export interface AppConfig {
  /** Whether authentication is required (set REQUIRE_AUTH=true to enable OAuth) */
  authRequired: boolean
  /** The NextAuth provider ID for signIn() calls (e.g. 'oauth', 'nvlogin', 'disabled-auth') */
  authProviderId: string
  /** Client-side session polling interval in seconds, derived from TOKEN_REFRESH_BUFFER_SECONDS */
  sessionRefreshIntervalSeconds: number
  /** File upload validation configuration */
  fileUpload: FileUploadConfig
}

const AppConfigContext = createContext<AppConfig | null>(null)

interface AppConfigProviderProps {
  config: AppConfig
  children: ReactNode
}

/**
 * Provider for runtime app configuration.
 * Wrap your app with this provider and pass config from a server component.
 */
export const AppConfigProvider = ({ config, children }: AppConfigProviderProps): ReactNode => {
  return <AppConfigContext.Provider value={config}>{children}</AppConfigContext.Provider>
}

/**
 * Hook to access runtime app configuration.
 * Must be used within an AppConfigProvider.
 *
 * @throws Error if used outside of AppConfigProvider
 */
export const useAppConfig = (): AppConfig => {
  const config = useContext(AppConfigContext)
  if (config === null) {
    throw new Error('useAppConfig must be used within an AppConfigProvider')
  }
  return config
}
