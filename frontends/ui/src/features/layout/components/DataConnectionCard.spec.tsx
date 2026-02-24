// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect } from 'vitest'
import { DataConnectionCard } from './DataConnectionCard'
import type { DataSource } from '../data-sources'

const mockSource: DataSource = {
  id: 'bug_tracker',
  name: 'Bug Tracker',
  description: 'Bug Tracking System',
  category: 'enterprise',
  defaultEnabled: true,
}

describe('DataConnectionCard', () => {
  test('renders source name and description', () => {
    render(<DataConnectionCard source={mockSource} isEnabled={false} onToggle={vi.fn()} />)

    expect(screen.getByText('Bug Tracker')).toBeInTheDocument()
    expect(screen.getByText('Bug Tracking System')).toBeInTheDocument()
  })

  test('renders switch in enabled state', () => {
    render(<DataConnectionCard source={mockSource} isEnabled={true} onToggle={vi.fn()} />)

    const switchEl = screen.getByRole('switch')
    expect(switchEl).toBeChecked()
  })

  test('renders switch in disabled state', () => {
    render(<DataConnectionCard source={mockSource} isEnabled={false} onToggle={vi.fn()} />)

    const switchEl = screen.getByRole('switch')
    expect(switchEl).not.toBeChecked()
  })

  test('calls onToggle when switch is clicked', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    render(<DataConnectionCard source={mockSource} isEnabled={false} onToggle={onToggle} />)

    await user.click(screen.getByRole('switch'))

    expect(onToggle).toHaveBeenCalledWith('bug_tracker', true)
  })

  test('calls onToggle when card is clicked', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    render(<DataConnectionCard source={mockSource} isEnabled={false} onToggle={onToggle} />)

    await user.click(screen.getByRole('button'))

    expect(onToggle).toHaveBeenCalledWith('bug_tracker', true)
  })

  test('disables switch when source is unavailable', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isAvailable={false}
        onToggle={vi.fn()}
      />
    )

    const switchEl = screen.getByRole('switch')
    expect(switchEl).toBeDisabled()
  })

  test('does not call onToggle when unavailable', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isAvailable={false}
        onToggle={onToggle}
      />
    )

    // Card click should not call onToggle when unavailable
    await user.click(screen.getByRole('button'))

    expect(onToggle).not.toHaveBeenCalled()
  })

  test('has correct aria-label for card', () => {
    render(<DataConnectionCard source={mockSource} isEnabled={true} onToggle={vi.fn()} />)

    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'Bug Tracker: enabled')
  })

  test('has correct aria-pressed attribute', () => {
    render(<DataConnectionCard source={mockSource} isEnabled={true} onToggle={vi.fn()} />)

    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })

  test('shows tooltip for unavailable sources', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isAvailable={false}
        onToggle={vi.fn()}
      />
    )

    // Card should still render but with disabled styling
    expect(screen.getByText('Bug Tracker')).toBeInTheDocument()
  })
})

describe('DataConnectionCard - Busy Session State', () => {
  const mockSource = {
    id: 'bug_tracker',
    name: 'Bug Tracker',
    description: 'Search bug database',
    category: 'enterprise' as const,
    defaultEnabled: false,
  }

  test('disables switch when session is busy', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={true}
        isBusy={true}
        onToggle={vi.fn()}
      />
    )

    const switchEl = screen.getByRole('switch')
    expect(switchEl).toBeDisabled()
  })

  test('does not call onToggle when busy and card is clicked', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isBusy={true}
        onToggle={onToggle}
      />
    )

    await user.click(screen.getByRole('button'))

    expect(onToggle).not.toHaveBeenCalled()
  })

  test('renders with busy tooltip content', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={true}
        isBusy={true}
        onToggle={vi.fn()}
      />
    )

    // Check that card is disabled
    const card = screen.getByRole('button')
    expect(card).toHaveAttribute('aria-disabled', 'true')
  })

  test('prioritizes busy state over unavailable state', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isAvailable={false}
        isBusy={true}
        unavailableReason="No permission"
        onToggle={vi.fn()}
      />
    )

    // Card should be disabled and show busy state
    const card = screen.getByRole('button')
    expect(card).toHaveAttribute('aria-disabled', 'true')
    expect(card).toHaveClass('cursor-not-allowed')
  })

  test('enables switch when session is not busy and source is available', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={true}
        isBusy={false}
        isAvailable={true}
        onToggle={vi.fn()}
      />
    )

    const switchEl = screen.getByRole('switch')
    expect(switchEl).not.toBeDisabled()
  })

  test('calls onToggle when not busy and clicked', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isBusy={false}
        onToggle={onToggle}
      />
    )

    await user.click(screen.getByRole('button'))

    expect(onToggle).toHaveBeenCalledWith('bug_tracker', true)
  })

  test('is not disabled when not busy and available', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={false}
        isBusy={false}
        onToggle={vi.fn()}
      />
    )

    const card = screen.getByRole('button')
    expect(card).not.toHaveAttribute('aria-disabled', 'true')
    expect(card).toHaveClass('cursor-pointer')
  })

  test('has correct aria-disabled when busy', () => {
    render(
      <DataConnectionCard
        source={mockSource}
        isEnabled={true}
        isBusy={true}
        onToggle={vi.fn()}
      />
    )

    expect(screen.getByRole('button')).toHaveAttribute('aria-disabled', 'true')
  })
})

