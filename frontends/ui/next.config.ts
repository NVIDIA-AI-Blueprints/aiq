// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { NextConfig } from 'next'

const fileUploadMaxSizeMB = parseInt(process.env.FILE_UPLOAD_MAX_SIZE_MB || '100', 10)

const nextConfig: NextConfig = {
  reactStrictMode: true,

  experimental: {
    serverActions: {
      bodySizeLimit: `${fileUploadMaxSizeMB}mb`,
    },
    proxyClientMaxBodySize: `${fileUploadMaxSizeMB}mb`,
  },

  turbopack: {},
}

export default nextConfig
