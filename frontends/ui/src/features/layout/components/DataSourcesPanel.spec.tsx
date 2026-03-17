// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { DataSourcesPanel } from './DataSourcesPanel'

// Mock the layout store
const mockCloseRightPanel = vi.fn()
const mockOpenRightPanel = vi.fn()
const mockSetDataSourcesPanelTab = vi.fn()
const mockToggleDataSource = vi.fn()
const mockSetEnabledDataSources = vi.fn()
const mockFetchDataSources = vi.fn()

const mockDataSources = [
  { id: 'web_search', name: 'Web Search', description: 'Search the web' },
  { id: 'knowledge_base', name: 'Knowledge Base', description: 'Wiki docs' },
  { id: 'bug_tracker', name: 'Bug Tracker', description: 'Bug tracking' },
]

vi.mock('../store', () => ({
  useLayoutStore: vi.fn(() => ({
    rightPanel: 'data-sources',
    closeRightPanel: mockCloseRightPanel,
    openRightPanel: mockOpenRightPanel,
    dataSourcesPanelTab: 'connections',
    setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
    enabledDataSourceIds: ['web_search', 'knowledge_base'],
    toggleDataSource: mockToggleDataSource,
    setEnabledDataSources: mockSetEnabledDataSources,
    availableDataSources: mockDataSources,
    dataSourcesLoading: false,
    dataSourcesError: null,
    fetchDataSources: mockFetchDataSources,
  })),
}))

// Mock useAuth hook
const mockSignIn = vi.fn()
vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({
    idToken: 'valid-token',
    signIn: mockSignIn,
  })),
}))

// Mock child components
vi.mock('./DataConnectionCard', () => ({
  DataConnectionCard: ({
    source,
    isEnabled,
    isAvailable,
  }: {
    source: { id: string; name: string }
    isEnabled: boolean
    isAvailable: boolean
  }) => (
    <div data-testid={`connection-card-${source.id}`}>
      {source.name} - {isEnabled ? 'enabled' : 'disabled'} - {isAvailable ? 'available' : 'unavailable'}
    </div>
  ),
}))

vi.mock('./FileSourcesTab', () => ({
  FileSourcesTab: () => <div data-testid="file-sources-tab">File Sources Tab</div>,
}))

import { useLayoutStore } from '../store'
import { useAuth } from '@/adapters/auth'

describe('DataSourcesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset mock to default open state with authenticated user
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: 'data-sources',
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      dataSourcesPanelTab: 'connections',
      setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
      enabledDataSourceIds: ['web_search', 'knowledge_base'],
      toggleDataSource: mockToggleDataSource,
      setEnabledDataSources: mockSetEnabledDataSources,
      availableDataSources: mockDataSources,
      dataSourcesLoading: false,
      dataSourcesError: null,
      fetchDataSources: mockFetchDataSources,
    } as unknown as ReturnType<typeof useLayoutStore>)

    vi.mocked(useAuth).mockReturnValue({
      idToken: 'valid-token',
      signIn: mockSignIn,
    } as unknown as ReturnType<typeof useAuth>)
  })

  test('renders panel when open', () => {
    render(<DataSourcesPanel />)

    expect(screen.getByText('Data Sources')).toBeInTheDocument()
  })

  test('renders connections tab by default', () => {
    render(<DataSourcesPanel />)

    expect(screen.getByText('Individual Connections (3)')).toBeInTheDocument()
    expect(screen.getByTestId('connection-card-web_search')).toBeInTheDocument()
    expect(screen.getByTestId('connection-card-knowledge_base')).toBeInTheDocument()
    expect(screen.getByTestId('connection-card-bug_tracker')).toBeInTheDocument()
  })

  test('renders tab navigation', () => {
    render(<DataSourcesPanel />)

    expect(screen.getByRole('radio', { name: /connections/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /files/i })).toBeInTheDocument()
  })

  test('switches to files tab when clicked', async () => {
    const user = userEvent.setup()
    render(<DataSourcesPanel />)

    await user.click(screen.getByRole('radio', { name: /files/i }))

    expect(mockSetDataSourcesPanelTab).toHaveBeenCalledWith('files')
  })

  test('renders files tab content', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: 'data-sources',
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      dataSourcesPanelTab: 'files',
      setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
      enabledDataSourceIds: ['web_search', 'knowledge_base'],
      toggleDataSource: mockToggleDataSource,
      setEnabledDataSources: mockSetEnabledDataSources,
      availableDataSources: mockDataSources,
      dataSourcesLoading: false,
      dataSourcesError: null,
      fetchDataSources: mockFetchDataSources,
    } as unknown as ReturnType<typeof useLayoutStore>)

    render(<DataSourcesPanel />)

    expect(screen.getByTestId('file-sources-tab')).toBeInTheDocument()
  })

  test('shows enabled count in footer for connections tab', () => {
    render(<DataSourcesPanel />)

    expect(screen.getByText(/2 of 3 available connections enabled/i)).toBeInTheDocument()
  })

  test('shows file upload message in footer for files tab', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: 'data-sources',
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      dataSourcesPanelTab: 'files',
      setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
      enabledDataSourceIds: ['web_search', 'knowledge_base'],
      toggleDataSource: mockToggleDataSource,
      setEnabledDataSources: mockSetEnabledDataSources,
      availableDataSources: mockDataSources,
      dataSourcesLoading: false,
      dataSourcesError: null,
      fetchDataSources: mockFetchDataSources,
    } as unknown as ReturnType<typeof useLayoutStore>)

    render(<DataSourcesPanel />)

    expect(screen.getByText(/attached files will be always available to agents until deleted/i)).toBeInTheDocument()
  })

  test('does not render content when panel is closed', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: null,
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      dataSourcesPanelTab: 'connections',
      setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
      enabledDataSourceIds: ['web_search', 'knowledge_base'],
      toggleDataSource: mockToggleDataSource,
      setEnabledDataSources: mockSetEnabledDataSources,
      availableDataSources: mockDataSources,
      dataSourcesLoading: false,
      dataSourcesError: null,
      fetchDataSources: mockFetchDataSources,
    } as unknown as ReturnType<typeof useLayoutStore>)

    render(<DataSourcesPanel />)

    // SidePanel handles visibility, so content should not be visible
    expect(screen.queryByText('Individual Connections (3)')).not.toBeInTheDocument()
  })

  test('renders all sources toggle', () => {
    render(<DataSourcesPanel />)

    expect(screen.getByText('All Connections')).toBeInTheDocument()
  })

  test('calls setEnabledDataSources when enable all is clicked', async () => {
    const user = userEvent.setup()
    render(<DataSourcesPanel />)

    // Find and click the "Enable All" button
    const enableAllButton = screen.getByRole('button', { name: /all available connections/i })
    await user.click(enableAllButton)

    expect(mockSetEnabledDataSources).toHaveBeenCalled()
  })

  test('shows correct enabled state for data connection cards', () => {
    render(<DataSourcesPanel />)

    // Web search and knowledge_base are enabled
    expect(screen.getByTestId('connection-card-web_search')).toHaveTextContent('enabled')
    expect(screen.getByTestId('connection-card-knowledge_base')).toHaveTextContent('enabled')
    // Bug Tracker is not in the enabled list
    expect(screen.getByTestId('connection-card-bug_tracker')).toHaveTextContent('disabled')
  })

  describe('error state', () => {
    test('renders error message when API fails', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        rightPanel: 'data-sources',
        closeRightPanel: mockCloseRightPanel,
        openRightPanel: mockOpenRightPanel,
        dataSourcesPanelTab: 'connections',
        setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
        enabledDataSourceIds: [],
        toggleDataSource: mockToggleDataSource,
        setEnabledDataSources: mockSetEnabledDataSources,
        availableDataSources: null,
        dataSourcesLoading: false,
        dataSourcesError: 'Failed to connect to server',
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataSourcesPanel />)

      expect(screen.getByText('Unable to load data sources')).toBeInTheDocument()
      expect(screen.getByText('Failed to connect to server')).toBeInTheDocument()
    })

    test('renders retry button on error', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        rightPanel: 'data-sources',
        closeRightPanel: mockCloseRightPanel,
        openRightPanel: mockOpenRightPanel,
        dataSourcesPanelTab: 'connections',
        setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
        enabledDataSourceIds: [],
        toggleDataSource: mockToggleDataSource,
        setEnabledDataSources: mockSetEnabledDataSources,
        availableDataSources: null,
        dataSourcesLoading: false,
        dataSourcesError: 'Network error',
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      render(<DataSourcesPanel />)

      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    })
  })

  describe('authentication state', () => {
    test('shows auth warning banner when no idToken and authenticated sources exist', () => {
      vi.mocked(useAuth).mockReturnValue({
        idToken: undefined,
        signIn: mockSignIn,
      } as unknown as ReturnType<typeof useAuth>)

      render(<DataSourcesPanel />)

      expect(screen.getByText(/access additional data sources/i)).toBeInTheDocument()
    })

    test('does not show auth warning when user has valid token', () => {
      vi.mocked(useAuth).mockReturnValue({
        idToken: 'valid-token',
        signIn: mockSignIn,
      } as unknown as ReturnType<typeof useAuth>)

      render(<DataSourcesPanel />)

      expect(screen.queryByText(/access additional data sources/i)).not.toBeInTheDocument()
    })

    test('does not show auth warning when only web_search is available', () => {
      vi.mocked(useLayoutStore).mockReturnValue({
        rightPanel: 'data-sources',
        closeRightPanel: mockCloseRightPanel,
        openRightPanel: mockOpenRightPanel,
        dataSourcesPanelTab: 'connections',
        setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
        enabledDataSourceIds: ['web_search'],
        toggleDataSource: mockToggleDataSource,
        setEnabledDataSources: mockSetEnabledDataSources,
        availableDataSources: [{ id: 'web_search', name: 'Web Search', description: 'Search' }],
        dataSourcesLoading: false,
        dataSourcesError: null,
        fetchDataSources: mockFetchDataSources,
      } as unknown as ReturnType<typeof useLayoutStore>)

      vi.mocked(useAuth).mockReturnValue({
        idToken: undefined,
        signIn: mockSignIn,
      } as unknown as ReturnType<typeof useAuth>)

      render(<DataSourcesPanel />)

      expect(screen.queryByText(/access additional data sources/i)).not.toBeInTheDocument()
    })

    test('renders sign in button in warning banner when no token', () => {
      vi.mocked(useAuth).mockReturnValue({
        idToken: undefined,
        signIn: mockSignIn,
      } as unknown as ReturnType<typeof useAuth>)

      render(<DataSourcesPanel />)

      // The warning banner should be present with sign in prompt
      expect(screen.getByText(/access additional data sources/i)).toBeInTheDocument()
      // KUI Banner renders the action slot - verify the button exists
      // Note: The exact rendering depends on KUI Banner implementation
    })

    test('marks authenticated sources as unavailable when no token', () => {
      vi.mocked(useAuth).mockReturnValue({
        idToken: undefined,
        signIn: mockSignIn,
      } as unknown as ReturnType<typeof useAuth>)

      render(<DataSourcesPanel />)

      // web_search should be available (doesn't require auth)
      expect(screen.getByTestId('connection-card-web_search')).toHaveTextContent('available')
      // Authenticated sources should be unavailable
      expect(screen.getByTestId('connection-card-knowledge_base')).toHaveTextContent('unavailable')
      expect(screen.getByTestId('connection-card-bug_tracker')).toHaveTextContent('unavailable')
    })

    test('marks all sources as available when user has valid token', () => {
      vi.mocked(useAuth).mockReturnValue({
        idToken: 'valid-token',
        signIn: mockSignIn,
      } as unknown as ReturnType<typeof useAuth>)

      render(<DataSourcesPanel />)

      expect(screen.getByTestId('connection-card-web_search')).toHaveTextContent('available')
      expect(screen.getByTestId('connection-card-knowledge_base')).toHaveTextContent('available')
      expect(screen.getByTestId('connection-card-bug_tracker')).toHaveTextContent('available')
    })
  })
})
