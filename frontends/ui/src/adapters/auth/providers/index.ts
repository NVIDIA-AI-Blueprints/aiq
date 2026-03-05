// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// ---------------------------------------------------------------------------
// Auth Providers  (no providers enabled)
// ---------------------------------------------------------------------------
//
// Authentication is disabled by default. The app runs with a default user
// and no login is required (REQUIRE_AUTH=false).
//
// This directory is the extension point for adding OAuth/OIDC providers.
// A complete InternalAuth provider implementation is preserved (commented out)
// in ./internal-auth.ts. To enable it:
//
//   1. Uncomment the code in ./internal-auth.ts
//   2. Re-export the symbols here:
//        export {
//          InternalAuthProvider,
//          getInternalAuthClientId,
//          getInternalAuthProviderId,
//          refreshInternalAuthToken,
//        } from './internal-auth'
//   3. Restore provider wiring in ../config.ts (imports + getAuthProvider)
//   4. Set AUTH_PROVIDER=internalauth and REQUIRE_AUTH=true in your env
//
// To add a custom OIDC provider, create a new file in this directory
// following the pattern in ./internal-auth.ts, export it here, and wire
// it into ../config.ts.
// ---------------------------------------------------------------------------
