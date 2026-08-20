// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach, afterEach } from 'vitest'
import { MermaidBlock } from './MermaidBlock'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'

const { initializeMock, renderMock } = vi.hoisted(() => ({
  initializeMock: vi.fn(),
  renderMock: vi.fn(async () => ({ svg: '<svg data-testid="mmd-svg"></svg>' })),
}))

vi.mock('mermaid', () => ({ default: { initialize: initializeMock, render: renderMock } }))

describe('MermaidBlock', () => {
  beforeEach(() => {
    initializeMock.mockClear()
    renderMock.mockClear()
    renderMock.mockResolvedValue({ svg: '<svg data-testid="mmd-svg"></svg>' })
  })

  afterEach(() => {
    document.documentElement.classList.remove('nv-dark', 'nv-light')
  })

  test('renders the diagram SVG and not the fallback', async () => {
    render(<MermaidBlock code={'erDiagram\n  A {\n  }'} fallback={<div>FALLBACK</div>} />)

    const diagram = await screen.findByRole('img', { name: 'Diagram' })
    expect(diagram.innerHTML).toContain('<svg')
    expect(screen.queryByText('FALLBACK')).not.toBeInTheDocument()
    expect(renderMock).toHaveBeenCalled()
  })

  test('falls back to the raw block when rendering fails', async () => {
    renderMock.mockRejectedValueOnce(new Error('parse error'))
    render(<MermaidBlock code={'not a diagram'} fallback={<div>FALLBACK</div>} />)

    expect(await screen.findByText('FALLBACK')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Diagram' })).not.toBeInTheDocument()
  })

  test('initializes with the light theme by default', async () => {
    render(<MermaidBlock code={'erDiagram'} fallback={<div />} />)
    await screen.findByRole('img', { name: 'Diagram' })

    expect(initializeMock).toHaveBeenCalledWith(
      expect.objectContaining({ theme: 'default', securityLevel: 'strict' })
    )
  })

  test('initializes with the dark theme when the app is in dark mode', async () => {
    document.documentElement.classList.add('nv-dark')
    render(<MermaidBlock code={'erDiagram'} fallback={<div />} />)
    await screen.findByRole('img', { name: 'Diagram' })

    expect(initializeMock).toHaveBeenCalledWith(expect.objectContaining({ theme: 'dark' }))
  })

  test('shows zoom controls and zooms in for a sized diagram', async () => {
    renderMock.mockResolvedValueOnce({ svg: '<svg viewBox="0 0 800 600"></svg>' })
    render(<MermaidBlock code={'erDiagram\n A { }'} fallback={<div />} />)
    await screen.findByRole('img', { name: 'Diagram' })

    expect(screen.getByLabelText('Zoom in')).toBeInTheDocument()
    expect(screen.getByLabelText('Reset zoom')).toHaveTextContent('100%')

    await userEvent.click(screen.getByLabelText('Zoom in'))
    expect(screen.getByLabelText('Reset zoom')).toHaveTextContent('125%')

    await userEvent.click(screen.getByLabelText('Zoom out'))
    expect(screen.getByLabelText('Reset zoom')).toHaveTextContent('100%')
  })

  test('expands to fullscreen and exits via the toggle and Escape', async () => {
    renderMock.mockResolvedValueOnce({ svg: '<svg viewBox="0 0 1600 900"></svg>' })
    render(<MermaidBlock code={'erDiagram\n A { }'} fallback={<div />} />)
    await screen.findByRole('img', { name: 'Diagram' })

    await userEvent.click(screen.getByLabelText('Expand to fullscreen'))
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
    const dialog = screen.getByRole('dialog', { name: 'Diagram fullscreen view' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')

    await userEvent.keyboard('{Escape}')
    expect(screen.getByLabelText('Expand to fullscreen')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  test('moves focus into the fullscreen dialog on open and restores it to the trigger on close', async () => {
    renderMock.mockResolvedValueOnce({ svg: '<svg viewBox="0 0 1600 900"></svg>' })
    render(<MermaidBlock code={'erDiagram\n A { }'} fallback={<div />} />)
    await screen.findByRole('img', { name: 'Diagram' })

    const trigger = screen.getByLabelText('Expand to fullscreen')
    trigger.focus()
    await userEvent.click(trigger)

    const dialog = screen.getByRole('dialog', { name: 'Diagram fullscreen view' })
    expect(dialog).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    expect(screen.getByLabelText('Expand to fullscreen')).toHaveFocus()
  })

  test('omits zoom controls when the diagram has no viewBox', async () => {
    renderMock.mockResolvedValueOnce({ svg: '<svg data-testid="mmd-svg"></svg>' })
    render(<MermaidBlock code={'erDiagram'} fallback={<div />} />)
    await screen.findByRole('img', { name: 'Diagram' })

    expect(screen.queryByLabelText('Zoom in')).not.toBeInTheDocument()
  })
})

describe('MarkdownRenderer mermaid routing', () => {
  beforeEach(() => {
    renderMock.mockResolvedValue({ svg: '<svg data-testid="mmd-svg"></svg>' })
  })

  test('renders a ```mermaid fenced block as a diagram', async () => {
    render(<MarkdownRenderer content={'```mermaid\nerDiagram\n  A {\n  }\n```'} />)
    expect(await screen.findByRole('img', { name: 'Diagram' })).toBeInTheDocument()
  })

  test('does not treat a non-mermaid code block as a diagram', () => {
    render(<MarkdownRenderer content={'```python\nprint(1)\n```'} />)
    expect(screen.queryByRole('img', { name: 'Diagram' })).not.toBeInTheDocument()
  })
})
