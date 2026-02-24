// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect } from 'vitest'
import { DeleteSessionConfirmationModal } from './DeleteSessionConfirmationModal'

describe('DeleteSessionConfirmationModal', () => {
  test('renders modal when open', () => {
    render(
      <DeleteSessionConfirmationModal open={true} onOpenChange={vi.fn()} onConfirm={vi.fn()} />
    )

    expect(screen.getByText('Deleting Session')).toBeInTheDocument()
    expect(screen.getByText(/you are about to delete this session/i)).toBeInTheDocument()
    expect(screen.getByText(/this action cannot be reversed/i)).toBeInTheDocument()
  })

  test('does not render when closed', () => {
    render(
      <DeleteSessionConfirmationModal open={false} onOpenChange={vi.fn()} onConfirm={vi.fn()} />
    )

    expect(screen.queryByText('Deleting Session')).not.toBeInTheDocument()
  })

  test('calls onConfirm and closes when delete is clicked', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const onOpenChange = vi.fn()

    render(
      <DeleteSessionConfirmationModal
        open={true}
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
      />
    )

    await user.click(screen.getByRole('button', { name: /delete session/i }))

    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  test('renders cancel button', () => {
    render(
      <DeleteSessionConfirmationModal open={true} onOpenChange={vi.fn()} onConfirm={vi.fn()} />
    )

    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
  })
})
