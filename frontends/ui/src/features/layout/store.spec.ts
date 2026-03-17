// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, beforeEach } from 'vitest'
import { useLayoutStore } from './store'

describe('useLayoutStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    useLayoutStore.setState({
      isSessionsPanelOpen: false,
      rightPanel: null,
      researchPanelTab: 'plan',
      dataSourcesPanelTab: 'connections',
      theme: 'system',
    })
  })

  describe('initial state', () => {
    test('has correct default values', () => {
      const state = useLayoutStore.getState()

      expect(state.isSessionsPanelOpen).toBe(false)
      expect(state.rightPanel).toBeNull()
      expect(state.researchPanelTab).toBe('plan')
      expect(state.dataSourcesPanelTab).toBe('connections')
    })
  })

  describe('toggleSessionsPanel', () => {
    test('opens sessions panel when closed', () => {
      useLayoutStore.getState().toggleSessionsPanel()

      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(true)
    })

    test('closes sessions panel when open', () => {
      useLayoutStore.setState({ isSessionsPanelOpen: true })

      useLayoutStore.getState().toggleSessionsPanel()

      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(false)
    })

    test('toggles multiple times correctly', () => {
      const { toggleSessionsPanel } = useLayoutStore.getState()

      toggleSessionsPanel()
      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(true)

      toggleSessionsPanel()
      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(false)

      toggleSessionsPanel()
      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(true)
    })
  })

  describe('setSessionsPanelOpen', () => {
    test('sets sessions panel to open', () => {
      useLayoutStore.getState().setSessionsPanelOpen(true)

      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(true)
    })

    test('sets sessions panel to closed', () => {
      useLayoutStore.setState({ isSessionsPanelOpen: true })

      useLayoutStore.getState().setSessionsPanelOpen(false)

      expect(useLayoutStore.getState().isSessionsPanelOpen).toBe(false)
    })
  })

  describe('openRightPanel', () => {
    test('opens research panel', () => {
      useLayoutStore.getState().openRightPanel('research')

      expect(useLayoutStore.getState().rightPanel).toBe('research')
    })

    test('opens data-sources panel', () => {
      useLayoutStore.getState().openRightPanel('data-sources')

      expect(useLayoutStore.getState().rightPanel).toBe('data-sources')
    })

    test('opens settings panel', () => {
      useLayoutStore.getState().openRightPanel('settings')

      expect(useLayoutStore.getState().rightPanel).toBe('settings')
    })

    test('replaces existing panel', () => {
      useLayoutStore.setState({ rightPanel: 'research' })

      useLayoutStore.getState().openRightPanel('settings')

      expect(useLayoutStore.getState().rightPanel).toBe('settings')
    })
  })

  describe('closeRightPanel', () => {
    test('closes open panel', () => {
      useLayoutStore.setState({ rightPanel: 'research' })

      useLayoutStore.getState().closeRightPanel()

      expect(useLayoutStore.getState().rightPanel).toBeNull()
    })

    test('handles closing when already closed', () => {
      useLayoutStore.getState().closeRightPanel()

      expect(useLayoutStore.getState().rightPanel).toBeNull()
    })
  })

  describe('setResearchPanelTab', () => {
    test('sets thinking tab', () => {
      useLayoutStore.getState().setResearchPanelTab('thinking')

      expect(useLayoutStore.getState().researchPanelTab).toBe('thinking')
    })

    test('sets citations tab', () => {
      useLayoutStore.getState().setResearchPanelTab('citations')

      expect(useLayoutStore.getState().researchPanelTab).toBe('citations')
    })

    test('sets report tab', () => {
      useLayoutStore.setState({ researchPanelTab: 'thinking' })

      useLayoutStore.getState().setResearchPanelTab('report')

      expect(useLayoutStore.getState().researchPanelTab).toBe('report')
    })
  })

  describe('setDataSourcesPanelTab', () => {
    test('sets connections tab', () => {
      useLayoutStore.setState({ dataSourcesPanelTab: 'files' })

      useLayoutStore.getState().setDataSourcesPanelTab('connections')

      expect(useLayoutStore.getState().dataSourcesPanelTab).toBe('connections')
    })

    test('sets files tab', () => {
      useLayoutStore.getState().setDataSourcesPanelTab('files')

      expect(useLayoutStore.getState().dataSourcesPanelTab).toBe('files')
    })
  })

  describe('setTheme', () => {
    test('sets light theme', () => {
      useLayoutStore.getState().setTheme('light')

      expect(useLayoutStore.getState().theme).toBe('light')
    })

    test('sets dark theme', () => {
      useLayoutStore.getState().setTheme('dark')

      expect(useLayoutStore.getState().theme).toBe('dark')
    })

    test('sets system theme', () => {
      useLayoutStore.setState({ theme: 'dark' })

      useLayoutStore.getState().setTheme('system')

      expect(useLayoutStore.getState().theme).toBe('system')
    })
  })
})
