// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react'
import { fireEvent, render, screen } from '@/test-utils'
import { describe, expect, test } from 'vitest'
import { CollapsibleBlock } from './CollapsibleBlock'

function Harness({ initialOpen = false }: { initialOpen?: boolean }) {
  const [open, setOpen] = useState(initialOpen)
  return (
    <CollapsibleBlock title="Trace" open={open} onOpenChange={setOpen}>
      <p>Body content</p>
    </CollapsibleBlock>
  )
}

describe('CollapsibleBlock', () => {
  test('hides the body and reflects a collapsed state when closed', () => {
    render(<Harness />)
    const toggle = screen.getByRole('button', { name: 'Trace' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Body content')).not.toBeInTheDocument()
  })

  test('drops aria-controls while collapsed so it never points at an unmounted region', () => {
    render(<Harness />)
    const toggle = screen.getByRole('button', { name: 'Trace' })
    expect(toggle).not.toHaveAttribute('aria-controls')
    fireEvent.click(toggle)
    const regionId = toggle.getAttribute('aria-controls')
    expect(regionId).toBeTruthy()
    expect(document.getElementById(regionId as string)).not.toBeNull()
  })

  test('toggles the body open and reveals it via the header button', () => {
    render(<Harness />)
    const toggle = screen.getByRole('button', { name: 'Trace' })
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Body content')).toBeInTheDocument()
  })

  test('wires aria-controls to the disclosed region id', () => {
    render(<Harness initialOpen />)
    const toggle = screen.getByRole('button', { name: 'Trace' })
    const regionId = toggle.getAttribute('aria-controls')
    expect(regionId).toBeTruthy()
    const region = document.getElementById(regionId as string)
    expect(region).not.toBeNull()
    expect(region).toHaveTextContent('Body content')
  })

  test('renders static without a toggle when not collapsible', () => {
    render(
      <CollapsibleBlock title="Static" open collapsible={false}>
        <p>Always visible</p>
      </CollapsibleBlock>,
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Always visible')).toBeInTheDocument()
  })
})
