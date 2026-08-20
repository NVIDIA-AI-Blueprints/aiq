// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  test('renders children', () => {
    render(<Card>hello</Card>)
    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  test('applies the shared surface and default tone', () => {
    const { container } = render(<Card>x</Card>)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('bg-surface-raised')
    expect(el.className).toContain('border-base')
  })

  test('source tones add an accent border without changing the base shape', () => {
    const { container } = render(<Card tone="web">x</Card>)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('border-l-[color:var(--text-color-subtle)]')
    expect(el.className).toContain('bg-surface-raised')
  })

  test('the doc tone accents the left border', () => {
    const { container } = render(<Card tone="doc">x</Card>)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('border-l-[color:var(--text-color-base)]')
  })

  test('the error tone uses the KUI feedback-danger token', () => {
    const { container } = render(<Card tone="error">x</Card>)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('border-[color:var(--border-color-feedback-danger)]')
    expect(el.className).not.toContain('text-color-error')
  })

  test('merges a caller className and forwards arbitrary props', () => {
    render(
      <Card className="p-2" data-testid="card" role="group">
        x
      </Card>,
    )
    const el = screen.getByTestId('card')
    expect(el).toHaveAttribute('role', 'group')
    expect(el.className).toContain('p-2')
    expect(el.className).not.toContain('p-4')
  })
})
