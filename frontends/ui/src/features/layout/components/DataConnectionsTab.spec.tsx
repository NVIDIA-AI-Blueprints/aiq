// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { DataConnectionsTab } from './DataConnectionsTab'

// Mock the layout store
const mockFetchDataSources = vi.fn()

vi.mock('../store', () => ({
  useLayoutStore: vi.fn(() => ({
    availableDataSources: [
      { id: 'web_search', name: 'Web Search', description: 'Search the web for information' },
      { id: 'knowledge_base', name: 'Knowledge Base', description: 'Search knowledge base wikis' },
      { id: 'document_store', name: 'Document Store', description: 'Search document store' },
    ],
    dataSourcesLoading: false,
    dataSourcesError: null,
    fetchDataSources: mockFetchDataSources,
  })),
}))

// Mock DataConnectionCard
vi.mock('./DataConnectionCard', () => ({
  DataConnectionCard: ({
    source,
    isEnabled,
    isAvailable,
    onToggle,
  }: {
    source: { id: string; name: string }
    isEnabled: boolean
    isAvailable: boolean
    onToggle: (id: string, enabled: boolean) => void
  }) => (
    <div data-testid="data-connection-card" data-available={isAvailable}>
      <span>{source.name}</span>
      <span data-testid={`enabled-${source.id}`}>{isEnabled ? 'enabled' : 'disabled'}</span>
      <button
        onClick={() => isAvailable && onToggle(source.id, !isEnabled)}
        data-testid={`toggle-${source.id}`}
        disabled={!isAvailable}
      >
        Toggle
      </button>
    </div>
  ),
}))

import { useLayoutStore } from '../store'

describe('DataConnectionsTab', () => {
  const mockOnToggle = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    // Reset to default state with data sources
    vi.mocked(useLayoutStore).mockReturnValue({
      availableDataSources: [
        { id: 'web_search', name: 'Web Search', description: 'Search the web for information' },
        { id: 'knowledge_base', name: 'Knowledge Base', description: 'Search knowledge base wikis' },
        { id: 'document_store', name: 'Document Store', description: 'Search document store' },
      ],
      dataSourcesLoading: false,
      dataSourcesError: null,
      fetchDataSources: mockFetchDataSources,
    } as unknown as ReturnType<typeof useLayoutStore>)
  })

  describe('rendering', () => {
    test('renders header with source count', () => {
      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByText('Available Sources (3)')).toBeInTheDocument()
    })

    test('renders all data source cards', () => {
      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByText('Web Search')).toBeInTheDocument()
      expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
      expect(screen.getByText('Document Store')).toBeInTheDocument()
    })

    test('renders correct number of cards', () => {
      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getAllByTestId('data-connection-card')).toHaveLength(3)
    })
  })

  describe('loading state', () => {
    test('renders loading spinner when loading', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        availableDataSources: null,
        dataSourcesLoading: true,
        dataSourcesError: null,
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByLabelText('Loading data sources')).toBeInTheDocument()
      expect(screen.getByText('Loading data sources...')).toBeInTheDocument()
    })
  })

  describe('error state', () => {
    test('renders error message when API fails', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        availableDataSources: null,
        dataSourcesLoading: false,
        dataSourcesError: 'Failed to connect to server',
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByText('Unable to load data sources')).toBeInTheDocument()
      expect(screen.getByText('Failed to connect to server')).toBeInTheDocument()
    })

    test('renders retry button on error', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        availableDataSources: null,
        dataSourcesLoading: false,
        dataSourcesError: 'Network error',
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    })

    test('calls fetchDataSources when retry is clicked', async () => {
      const user = userEvent.setup()
      vi.mocked(useLayoutStore).mockReturnValue({
        availableDataSources: null,
        dataSourcesLoading: false,
        dataSourcesError: 'Network error',
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      await user.click(screen.getByRole('button', { name: /retry/i }))

      expect(mockFetchDataSources).toHaveBeenCalled()
    })
  })

  describe('empty state', () => {
    test('renders empty state when no sources available', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        availableDataSources: [],
        dataSourcesLoading: false,
        dataSourcesError: null,
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByText('No data sources available')).toBeInTheDocument()
    })
  })

  describe('enabled state', () => {
    test('passes enabled state for enabled sources', () => {
      render(
        <DataConnectionsTab
          enabledSourceIds={new Set(['web_search', 'knowledge_base'])}
          onToggle={mockOnToggle}
        />
      )

      expect(screen.getByTestId('enabled-web_search')).toHaveTextContent('enabled')
      expect(screen.getByTestId('enabled-knowledge_base')).toHaveTextContent('enabled')
      expect(screen.getByTestId('enabled-document_store')).toHaveTextContent('disabled')
    })

    test('passes disabled state for disabled sources', () => {
      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      expect(screen.getByTestId('enabled-web_search')).toHaveTextContent('disabled')
      expect(screen.getByTestId('enabled-knowledge_base')).toHaveTextContent('disabled')
      expect(screen.getByTestId('enabled-document_store')).toHaveTextContent('disabled')
    })
  })

  describe('toggle callback', () => {
    test('calls onToggle when source is toggled', async () => {
      const user = userEvent.setup()

      render(<DataConnectionsTab enabledSourceIds={new Set()} onToggle={mockOnToggle} />)

      await user.click(screen.getByTestId('toggle-web_search'))

      expect(mockOnToggle).toHaveBeenCalledWith('web_search', true)
    })

    test('calls onToggle with correct state when disabling', async () => {
      const user = userEvent.setup()

      render(
        <DataConnectionsTab enabledSourceIds={new Set(['knowledge_base'])} onToggle={mockOnToggle} />
      )

      await user.click(screen.getByTestId('toggle-knowledge_base'))

      expect(mockOnToggle).toHaveBeenCalledWith('knowledge_base', false)
    })
  })
})
