// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ReactElement } from 'react'
import { ThemeProvider } from '@nvidia/foundations-react-core'
import { render } from '@testing-library/react'

const TestProviders = ({ children }: { children: React.ReactNode }) => (
  <ThemeProvider theme="light">{children}</ThemeProvider>
)

const renderWithProviders = (ui: ReactElement) => {
  const { rerender, ...rest } = render(<TestProviders>{ui}</TestProviders>)
  return {
    ...rest,
    rerender: (rerenderUi: ReactElement) => rerender(<TestProviders>{rerenderUi}</TestProviders>),
  }
}

// Re-export everything from @testing-library/react
export * from '@testing-library/react'
// Override render with our custom wrapper
export { renderWithProviders as render }
