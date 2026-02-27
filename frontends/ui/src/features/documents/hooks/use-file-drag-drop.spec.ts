// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { useFileDragDrop } from './use-file-drag-drop'

// Mock the validation module
vi.mock('../validation', () => ({
  checkDraggedFilesSupported: vi.fn(() => true),
}))

// Mock useAppConfig
vi.mock('@/shared/context', () => ({
  useAppConfig: () => ({
    authRequired: true,
    fileUpload: {
      acceptedTypes: '.pdf,.docx,.txt,.md',
      acceptedMimeTypes: ['application/pdf', 'text/plain', 'text/markdown'],
      maxTotalSizeMB: 100,
      maxFileSize: 100 * 1024 * 1024,
      maxTotalSize: 100 * 1024 * 1024,
      maxFileCount: 10,
    },
  }),
}))

import { checkDraggedFilesSupported } from '../validation'

/**
 * Create a mock DragEvent with configurable dataTransfer
 */
function createMockDragEvent(files: File[] = [], items: DataTransferItem[] = []): React.DragEvent {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer: {
      files,
      items: items.length > 0 ? items : files.map(() => ({ kind: 'file', type: 'application/pdf' })),
    },
  } as unknown as React.DragEvent
}

describe('useFileDragDrop', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(checkDraggedFilesSupported).mockReturnValue(true)
  })

  test('returns initial state with isDragging false', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    expect(result.current.isDragging).toBe(false)
    expect(result.current.isUnsupportedDrag).toBe(false)
    expect(result.current.dragHandlers).toBeDefined()
    expect(result.current.dragHandlers.onDragEnter).toBeInstanceOf(Function)
    expect(result.current.dragHandlers.onDragLeave).toBeInstanceOf(Function)
    expect(result.current.dragHandlers.onDragOver).toBeInstanceOf(Function)
    expect(result.current.dragHandlers.onDrop).toBeInstanceOf(Function)
  })

  test('sets isDragging to true on dragEnter with files', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const mockEvent = createMockDragEvent(
      [new File(['content'], 'test.pdf', { type: 'application/pdf' })],
      [{ kind: 'file', type: 'application/pdf' } as DataTransferItem]
    )

    act(() => {
      result.current.dragHandlers.onDragEnter(mockEvent)
    })

    expect(result.current.isDragging).toBe(true)
    expect(mockEvent.preventDefault).toHaveBeenCalled()
    expect(mockEvent.stopPropagation).toHaveBeenCalled()
  })

  test('sets isUnsupportedDrag when files are unsupported', () => {
    vi.mocked(checkDraggedFilesSupported).mockReturnValue(false)

    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const mockEvent = createMockDragEvent(
      [new File(['content'], 'test.exe', { type: 'application/x-msdownload' })],
      [{ kind: 'file', type: 'application/x-msdownload' } as DataTransferItem]
    )

    act(() => {
      result.current.dragHandlers.onDragEnter(mockEvent)
    })

    expect(result.current.isDragging).toBe(true)
    expect(result.current.isUnsupportedDrag).toBe(true)
  })

  test('resets isDragging on dragLeave when counter reaches zero', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const enterEvent = createMockDragEvent(
      [new File(['content'], 'test.pdf', { type: 'application/pdf' })],
      [{ kind: 'file', type: 'application/pdf' } as DataTransferItem]
    )

    // Enter once
    act(() => {
      result.current.dragHandlers.onDragEnter(enterEvent)
    })
    expect(result.current.isDragging).toBe(true)

    // Leave once
    const leaveEvent = createMockDragEvent()
    act(() => {
      result.current.dragHandlers.onDragLeave(leaveEvent)
    })
    expect(result.current.isDragging).toBe(false)
  })

  test('keeps isDragging true with nested drag enter/leave', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const enterEvent = createMockDragEvent(
      [new File(['content'], 'test.pdf', { type: 'application/pdf' })],
      [{ kind: 'file', type: 'application/pdf' } as DataTransferItem]
    )
    const leaveEvent = createMockDragEvent()

    // Enter parent
    act(() => {
      result.current.dragHandlers.onDragEnter(enterEvent)
    })
    // Enter child
    act(() => {
      result.current.dragHandlers.onDragEnter(enterEvent)
    })
    expect(result.current.isDragging).toBe(true)

    // Leave child
    act(() => {
      result.current.dragHandlers.onDragLeave(leaveEvent)
    })
    // Should still be dragging (counter = 1)
    expect(result.current.isDragging).toBe(true)

    // Leave parent
    act(() => {
      result.current.dragHandlers.onDragLeave(leaveEvent)
    })
    // Now should be false (counter = 0)
    expect(result.current.isDragging).toBe(false)
  })

  test('calls onDrop with files and resets state', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    const enterEvent = createMockDragEvent(
      [file],
      [{ kind: 'file', type: 'application/pdf' } as DataTransferItem]
    )
    const dropEvent = createMockDragEvent([file])

    // Enter to set dragging state
    act(() => {
      result.current.dragHandlers.onDragEnter(enterEvent)
    })
    expect(result.current.isDragging).toBe(true)

    // Drop
    act(() => {
      result.current.dragHandlers.onDrop(dropEvent)
    })

    expect(onDrop).toHaveBeenCalledWith([file])
    expect(result.current.isDragging).toBe(false)
    expect(result.current.isUnsupportedDrag).toBe(false)
    expect(dropEvent.preventDefault).toHaveBeenCalled()
    expect(dropEvent.stopPropagation).toHaveBeenCalled()
  })

  test('does not call onDrop with empty files', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const dropEvent = createMockDragEvent([])

    act(() => {
      result.current.dragHandlers.onDrop(dropEvent)
    })

    expect(onDrop).not.toHaveBeenCalled()
  })

  test('does not trigger drag events when disabled', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop, disabled: true }))

    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    const enterEvent = createMockDragEvent(
      [file],
      [{ kind: 'file', type: 'application/pdf' } as DataTransferItem]
    )

    act(() => {
      result.current.dragHandlers.onDragEnter(enterEvent)
    })

    // Event handlers still called but state doesn't change
    expect(result.current.isDragging).toBe(false)
  })

  test('does not call onDrop when disabled', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop, disabled: true }))

    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    const dropEvent = createMockDragEvent([file])

    act(() => {
      result.current.dragHandlers.onDrop(dropEvent)
    })

    expect(onDrop).not.toHaveBeenCalled()
  })

  test('onDragOver prevents default', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const overEvent = createMockDragEvent()

    act(() => {
      result.current.dragHandlers.onDragOver(overEvent)
    })

    expect(overEvent.preventDefault).toHaveBeenCalled()
    expect(overEvent.stopPropagation).toHaveBeenCalled()
  })

  test('handles multiple files on drop', () => {
    const onDrop = vi.fn()
    const { result } = renderHook(() => useFileDragDrop({ onDrop }))

    const files = [
      new File(['content1'], 'test1.pdf', { type: 'application/pdf' }),
      new File(['content2'], 'test2.pdf', { type: 'application/pdf' }),
      new File(['content3'], 'test3.txt', { type: 'text/plain' }),
    ]
    const dropEvent = createMockDragEvent(files)

    act(() => {
      result.current.dragHandlers.onDrop(dropEvent)
    })

    expect(onDrop).toHaveBeenCalledWith(files)
    expect(onDrop).toHaveBeenCalledTimes(1)
  })
})
