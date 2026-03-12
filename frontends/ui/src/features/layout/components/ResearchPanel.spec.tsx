// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ResearchPanel } from './ResearchPanel'

// Mock the stores
const mockCloseRightPanel = vi.fn()
const mockOpenRightPanel = vi.fn()
const mockSetResearchPanelTab = vi.fn()
let mockRightPanel: string | null = 'research'
let mockResearchPanelTab = 'tasks'

vi.mock('../store', () => ({
  useLayoutStore: () => ({
    rightPanel: mockRightPanel,
    researchPanelTab: mockResearchPanelTab,
    setResearchPanelTab: mockSetResearchPanelTab,
    closeRightPanel: mockCloseRightPanel,
    openRightPanel: mockOpenRightPanel,
  }),
}))

vi.mock('@/adapters/auth', () => ({
  useAuth: vi.fn(() => ({ idToken: 'mock-token' })),
}))

vi.mock('@/adapters/api', () => ({
  cancelJob: vi.fn().mockResolvedValue(undefined),
}))

let mockIsDeepResearchStreaming = false
let mockDeepResearchJobId: string | null = null
let mockDeepResearchStreamLoaded = false
const mockImportJobStream = vi.fn()

const mockCancelCurrentJob = vi.fn()

vi.mock('@/features/chat', () => ({
  useChatStore: (selector: (state: {
    isDeepResearchStreaming: boolean
    deepResearchJobId: string | null
    deepResearchStreamLoaded: boolean
  }) => unknown) =>
    selector({
      isDeepResearchStreaming: mockIsDeepResearchStreaming,
      deepResearchJobId: mockDeepResearchJobId,
      deepResearchStreamLoaded: mockDeepResearchStreamLoaded,
    }),
  useLoadJobData: () => ({
    importStreamOnly: mockImportJobStream,
    isLoading: false,
  }),
  useDeepResearch: () => ({
    cancelCurrentJob: mockCancelCurrentJob,
  }),
}))

// Mock the tab components
vi.mock('./PlanTab', () => ({
  PlanTab: () => <div data-testid="plan-tab">Plan Tab Content</div>,
}))

vi.mock('./TasksTab', () => ({
  TasksTab: () => <div data-testid="tasks-tab">Tasks Tab Content</div>,
}))

vi.mock('./ThinkingTab', () => ({
  ThinkingTab: () => <div data-testid="thinking-tab">Thinking Tab Content</div>,
}))

vi.mock('./CitationsTab', () => ({
  CitationsTab: () => <div data-testid="citations-tab">Citations Tab Content</div>,
}))

vi.mock('./ReportTab', () => ({
  ReportTab: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="report-tab">Report Tab Content {children}</div>
  ),
}))

describe('ResearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRightPanel = 'research'
    mockResearchPanelTab = 'tasks'
    mockIsDeepResearchStreaming = false
    mockDeepResearchJobId = null
    mockDeepResearchStreamLoaded = false
    mockImportJobStream.mockClear()
  })

  describe('panel visibility', () => {
    test('renders when rightPanel is "research"', () => {
      mockRightPanel = 'research'

      render(<ResearchPanel isAuthenticated={true} />)

      // Panel should be visible - toggle button and close button should be present
      expect(screen.getByTestId('research-panel-toggle')).toBeInTheDocument()
      expect(screen.getByTestId('research-panel-close')).toBeInTheDocument()
    })

    test('is hidden when rightPanel is null', () => {
      mockRightPanel = null

      const { container } = render(<ResearchPanel isAuthenticated={true} />)

      // Find the outer container with aria-hidden
      const outerPanel = container.querySelector('[aria-hidden="true"]')
      expect(outerPanel).toBeInTheDocument()
    })
  })

  describe('tab navigation', () => {
    test('renders all tab options', () => {
      render(<ResearchPanel isAuthenticated={true} />)

      expect(screen.getByText('Plan')).toBeInTheDocument()
      expect(screen.getByText('Tasks')).toBeInTheDocument()
      expect(screen.getByText('Thinking')).toBeInTheDocument()
      expect(screen.getByText('Citations')).toBeInTheDocument()
      expect(screen.getByText('Report')).toBeInTheDocument()
    })

    test('calls setResearchPanelTab when tab is clicked', async () => {
      const user = userEvent.setup()

      render(<ResearchPanel isAuthenticated={true} />)

      await user.click(screen.getByText('Plan'))
      expect(mockSetResearchPanelTab).toHaveBeenCalledWith('plan')

      await user.click(screen.getByText('Thinking'))
      expect(mockSetResearchPanelTab).toHaveBeenCalledWith('thinking')

      await user.click(screen.getByText('Citations'))
      expect(mockSetResearchPanelTab).toHaveBeenCalledWith('citations')
    })

    test('displays correct tab content based on researchPanelTab', () => {
      mockResearchPanelTab = 'tasks'
      const { rerender } = render(<ResearchPanel isAuthenticated={true} />)
      expect(screen.getByTestId('tasks-tab')).toBeInTheDocument()

      mockResearchPanelTab = 'plan'
      rerender(<ResearchPanel isAuthenticated={true} />)
      expect(screen.getByTestId('plan-tab')).toBeInTheDocument()

      mockResearchPanelTab = 'thinking'
      rerender(<ResearchPanel isAuthenticated={true} />)
      expect(screen.getByTestId('thinking-tab')).toBeInTheDocument()

      mockResearchPanelTab = 'citations'
      rerender(<ResearchPanel isAuthenticated={true} />)
      expect(screen.getByTestId('citations-tab')).toBeInTheDocument()

      mockResearchPanelTab = 'report'
      rerender(<ResearchPanel isAuthenticated={true} />)
      expect(screen.getByTestId('report-tab')).toBeInTheDocument()
    })
  })

  describe('close button', () => {
    test('renders close button', () => {
      render(<ResearchPanel isAuthenticated={true} />)

      expect(screen.getByTestId('research-panel-close')).toBeInTheDocument()
    })

    test('calls closeRightPanel when close button clicked', async () => {
      const user = userEvent.setup()

      render(<ResearchPanel isAuthenticated={true} />)

      await user.click(screen.getByTestId('research-panel-close'))

      expect(mockCloseRightPanel).toHaveBeenCalled()
    })
  })

  describe('stop researching button', () => {
    test('is always rendered', () => {
      mockIsDeepResearchStreaming = false

      render(<ResearchPanel isAuthenticated={true} />)

      expect(screen.getByTestId('research-panel-stop')).toBeInTheDocument()
    })

    test('is disabled when not streaming', () => {
      mockIsDeepResearchStreaming = false

      render(<ResearchPanel isAuthenticated={true} />)

      expect(screen.getByTestId('research-panel-stop')).toBeDisabled()
    })

    test('is enabled when streaming', () => {
      mockIsDeepResearchStreaming = true

      render(<ResearchPanel isAuthenticated={true} />)

      expect(screen.getByTestId('research-panel-stop')).not.toBeDisabled()
    })
  })

  describe('streaming indicator', () => {
    test('shows spinner in toggle tag when streaming', () => {
      mockIsDeepResearchStreaming = true

      render(<ResearchPanel isAuthenticated={true} />)

      // Spinner is now in the toggle tag button
      expect(screen.getByLabelText('Researching')).toBeInTheDocument()
    })

    test('shows generate icon when not streaming', () => {
      mockIsDeepResearchStreaming = false

      render(<ResearchPanel isAuthenticated={true} />)

      // When not streaming, the generate icon is shown instead of spinner
      expect(screen.queryByLabelText('Researching')).not.toBeInTheDocument()
    })
  })

  describe('children rendering', () => {
    test('passes children to ReportTab', () => {
      mockResearchPanelTab = 'report'

      render(
        <ResearchPanel isAuthenticated={true}>
          <div data-testid="custom-content">Custom Content</div>
        </ResearchPanel>
      )

      expect(screen.getByTestId('custom-content')).toBeInTheDocument()
    })
  })

  describe('segmented control groups', () => {
    test('has all tab options', () => {
      render(<ResearchPanel isAuthenticated={true} />)

      expect(screen.getByText('Plan')).toBeInTheDocument()
      expect(screen.getByText('Tasks')).toBeInTheDocument()
      expect(screen.getByText('Thinking')).toBeInTheDocument()
      expect(screen.getByText('Citations')).toBeInTheDocument()
      expect(screen.getByText('Report')).toBeInTheDocument()
    })
  })

  describe('toggle tag button', () => {
    test('renders toggle tag button', () => {
      render(<ResearchPanel isAuthenticated={true} />)

      // The toggle tag button has a specific data-testid
      expect(screen.getByTestId('research-panel-toggle')).toBeInTheDocument()
      expect(screen.getByText('Show Research')).toBeInTheDocument()
    })

    test('closes panel when tag clicked while open', async () => {
      mockRightPanel = 'research'
      const user = userEvent.setup()

      render(<ResearchPanel isAuthenticated={true} />)

      await user.click(screen.getByTestId('research-panel-toggle'))

      expect(mockCloseRightPanel).toHaveBeenCalled()
    })

    test('toggle button is disabled when not authenticated', () => {
      render(<ResearchPanel isAuthenticated={false} />)

      const toggleButton = screen.getByTestId('research-panel-toggle')
      expect(toggleButton).toBeDisabled()
      expect(toggleButton).toHaveAttribute('title', 'Sign in to access research panel')
    })

    test('toggle button does not trigger action when not authenticated', async () => {
      mockRightPanel = null
      const user = userEvent.setup()

      render(<ResearchPanel isAuthenticated={false} />)

      await user.click(screen.getByTestId('research-panel-toggle'))

      expect(mockOpenRightPanel).not.toHaveBeenCalled()
    })
  })
})
