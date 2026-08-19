// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import type { DeepResearchAgent } from '../types'
import { deriveResearchProgress } from './deep-research-progress'

const agent = (
  name: string,
  status: DeepResearchAgent['status'] = 'complete',
  id = name
): DeepResearchAgent => ({
  id,
  name,
  status,
  startedAt: new Date('2026-01-01T00:00:00Z'),
  ...(status === 'complete' && { completedAt: new Date('2026-01-01T00:01:00Z') }),
})

const statuses = (progress: ReturnType<typeof deriveResearchProgress>) =>
  progress?.map((phase) => phase.status)

describe('deriveResearchProgress', () => {
  test('uses the legacy fallback for an inactive job without a recognized trace', () => {
    expect(deriveResearchProgress([], null, false)).toBeNull()
    expect(deriveResearchProgress([agent('custom-agent')], 'success', false)).toBeNull()
  })

  test('returns an empty observed timeline while an active job awaits its first workflow', () => {
    expect(deriveResearchProgress([], 'submitted', true)).toEqual([])
    expect(deriveResearchProgress([agent('custom-agent')], 'running', true)).toEqual([])
  })

  test('tracks only the observed source-router lifecycle', () => {
    expect(deriveResearchProgress([agent('source-router-agent', 'running')], 'running', true)).toEqual(
      [
        {
          id: 'phase:routing',
          content: 'Routing sources',
          status: 'in_progress',
        },
      ]
    )
    expect(statuses(deriveResearchProgress([agent('source-router-agent')], 'running', true))).toEqual([
      'completed',
    ])
  })

  test('supports a planner-first workflow without synthesizing source routing', () => {
    const progress = deriveResearchProgress([agent('planner-agent', 'running')], 'running', true)

    expect(progress).toEqual([
      {
        id: 'phase:planning',
        content: 'Planning',
        status: 'in_progress',
      },
    ])
  })

  test('keeps phases in first-observed order', () => {
    const progress = deriveResearchProgress(
      [agent('writer-agent', 'running'), agent('planner-agent', 'running')],
      'running',
      true
    )

    expect(progress?.map((phase) => phase.id)).toEqual(['phase:writing', 'phase:planning'])
  })

  test('does not fabricate planning or research when a run jumps from routing to writing', () => {
    const progress = deriveResearchProgress(
      [agent('source-router-agent'), agent('writer-agent', 'running')],
      'running',
      true
    )

    expect(progress).toEqual([
      { id: 'phase:routing', content: 'Routing sources', status: 'completed' },
      { id: 'phase:writing', content: 'Writing the report', status: 'in_progress' },
    ])
  })

  test('aggregates parallel researchers into one observed phase', () => {
    const progress = deriveResearchProgress(
      [
        agent('researcher-agent', 'complete', 'researcher-1'),
        agent('researcher-agent', 'running', 'researcher-2'),
      ],
      'running',
      true
    )

    expect(progress).toEqual([
      {
        id: 'phase:research',
        content: 'Researching (1/2 researchers completed)',
        status: 'in_progress',
      },
    ])
  })

  test('reports zero and full researcher completion without inventing future researchers', () => {
    expect(
      deriveResearchProgress(
        [
          agent('researcher-agent', 'running', 'researcher-1'),
          agent('researcher-agent', 'running', 'researcher-2'),
        ],
        'running',
        true
      )?.[0]
    ).toMatchObject({
      content: 'Researching (0/2 researchers completed)',
      status: 'in_progress',
    })

    expect(
      deriveResearchProgress(
        [
          agent('researcher-agent', 'complete', 'researcher-1'),
          agent('researcher-agent', 'complete', 'researcher-2'),
        ],
        'running',
        true
      )?.[0]
    ).toMatchObject({
      content: 'Researching (2/2 researchers completed)',
      status: 'completed',
    })
  })

  test('aggregates retries and completes a phase only after every observed attempt ends', () => {
    const retrying = deriveResearchProgress(
      [
        agent('planner-agent', 'complete', 'planner-1'),
        agent('planner-agent', 'running', 'planner-2'),
      ],
      'running',
      true
    )
    const completed = deriveResearchProgress(
      [
        agent('planner-agent', 'complete', 'planner-1'),
        agent('planner-agent', 'complete', 'planner-2'),
      ],
      'running',
      true
    )

    expect(retrying).toHaveLength(1)
    expect(retrying?.[0].status).toBe('in_progress')
    expect(completed).toHaveLength(1)
    expect(completed?.[0].status).toBe('completed')
  })

  test('preserves overlapping phases when the workflow actually overlaps', () => {
    const progress = deriveResearchProgress(
      [agent('researcher-agent', 'running'), agent('writer-agent', 'running')],
      'running',
      true
    )

    expect(statuses(progress)).toEqual(['in_progress', 'in_progress'])
  })

  test.each(['failure', 'interrupted'] as const)(
    'preserves completed phases and stops unfinished observed phases on %s',
    (jobStatus) => {
      const progress = deriveResearchProgress(
        [agent('planner-agent'), agent('researcher-agent', 'running')],
        jobStatus,
        false
      )

      expect(statuses(progress)).toEqual(['completed', 'stopped'])
    }
  )

  test('does not complete a start-only workflow from terminal success alone', () => {
    const progress = deriveResearchProgress(
      [agent('source-router-agent'), agent('writer-agent', 'running')],
      'success',
      false
    )

    expect(statuses(progress)).toEqual(['completed', 'stopped'])
  })

  test('shows only observed completed phases for a successful job', () => {
    const progress = deriveResearchProgress([agent('writer-agent')], 'success', false)

    expect(progress).toEqual([
      { id: 'phase:writing', content: 'Writing the report', status: 'completed' },
    ])
  })
})
