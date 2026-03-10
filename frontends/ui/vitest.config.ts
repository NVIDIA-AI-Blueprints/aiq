// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import path from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    css: false,
    globals: true,
    environment: 'happy-dom',
    testTimeout: 50000,
    root: './',
    include: ['src/**/*.spec.{ts,tsx}'],
    exclude: ['**/mocks/**', '**/node_modules/**'],
    setupFiles: ['./config/vitest/polyfills.ts', './config/vitest/vitest.setup.ts'],
    clearMocks: true,
    server: {
      deps: {
        inline: [/@nvidia/],
      },
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'cobertura', 'html'],
      reportsDirectory: './coverage',
      exclude: [
        'node_modules/**',
        'config/**',
        '**/*.spec.{ts,tsx}',
        '**/mocks/**',
        '**/test-utils/**',
        '**/*.d.ts',
      ],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@/adapters': path.resolve(__dirname, './src/adapters'),
      '@/features': path.resolve(__dirname, './src/features'),
      '@/shared': path.resolve(__dirname, './src/shared'),
      'server-only': path.resolve(
        __dirname,
        './config/vitest/mocks/server-only.ts',
      ),
      'external-svg-loader': path.resolve(
        __dirname,
        './config/vitest/mocks/external-svg-loader.ts',
      ),
      'external-svg-loader/dist/svg-loader.min.js': path.resolve(
        __dirname,
        './config/vitest/mocks/external-svg-loader.ts',
      ),
    },
  },
})
