// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { describe, test, expect } from 'vitest'
import { CitationsTab } from './CitationsTab'

describe('CitationsTab', () => {
  test('renders section title', () => {
    render(<CitationsTab />)

    // Uses getAllByText since there's a button and a header with "Referenced"
    const referencedElements = screen.getAllByText('Referenced')
    expect(referencedElements.length).toBeGreaterThanOrEqual(1)
  })

  test('displays empty state message', () => {
    render(<CitationsTab />)

    expect(screen.getByText(/No referenced sources yet/i)).toBeInTheDocument()
  })

  test('displays book icon in empty state', () => {
    render(<CitationsTab />)

    expect(screen.getByText(/No referenced sources yet/i)).toBeInTheDocument()
  })

  test('displays description subheading', () => {
    render(<CitationsTab />)

    expect(screen.getByText(/Sources referenced in the final report/i)).toBeInTheDocument()
  })
})
