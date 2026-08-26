// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { CopyButton } from './CopyButton'

const writeText = vi.fn().mockResolvedValue(undefined)

describe('CopyButton', () => {
  beforeEach(() => {
    writeText.mockClear()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  })

  test('copies the provided text and confirms with a checkmark', async () => {
    render(<CopyButton text="There are 11,463 users." />)
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith('There are 11,463 users.')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument())
  })

  test('renders a custom label', () => {
    render(<CopyButton text="x" label="Copy answer" />)
    expect(screen.getByRole('button', { name: 'Copy answer' })).toBeInTheDocument()
  })

  test('does not throw when the clipboard API rejects', async () => {
    writeText.mockRejectedValueOnce(new Error('blocked'))
    render(<CopyButton text="x" />)
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })
})
