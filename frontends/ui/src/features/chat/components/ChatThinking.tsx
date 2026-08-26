// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ChatThinking Component
 *
 * The inline, live "what the agent is doing" surface shown under a user message.
 *
 * Instead of a flat wall of steps, the intermediate stream is folded into a
 * short spine of phases (top-level workflow steps). Each phase folds open to the
 * model / tool sub-calls it actually made, surfacing the human tool label and
 * the call's input so the user can read what happened. A single status atom
 * marks each node's lifecycle (running / done / error / waiting), and durations
 * appear only when they are real (>= ~1s). Expanded while the agent works,
 * collapsible once done. Drives both shallow and deep research from the same
 * step stream.
 */

'use client'

import { type FC, type ReactNode, useEffect, useId, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Flex, Text, AnimatedChevron, Spinner } from '@/adapters/ui'
import { CheckCircle, Warning, Clock } from '@/adapters/ui/icons'
import { SourceKindIcon } from '@/shared/components/Sources/SourceKindIcon'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import { type NodeState, ToolCallRow, getToolLabel, isKnownTool } from '@/shared/components/research'
import { getDataSourceKind, getDataSourceLabel } from '@/features/layout/data-sources'
import type { SourceKind } from '@/shared/components/Sources/types'
import { cn } from '@/shared/lib/cn'
import {
  extractFoldedOutput,
  isExplanationStep,
  isFoldedTextStep,
  isLLMModel,
  isReasoningStep,
  isReflectionStep,
} from '../lib/intermediate-step-parser'
import type { ThinkingStep } from '../types'

export interface ChatThinkingProps {
  steps: ThinkingStep[]
  isThinking?: boolean
  isInterrupted?: boolean
  isWaiting?: boolean
  enabledDataSources?: string[]
  messageFiles?: Array<{ id: string; fileName: string }>
  /** Final-response model selected for the user turn that owns these steps. */
  model?: string
  /** Wall-clock start and completion timestamps for the entire response. */
  responseStartedAt?: Date | string
  responseCompletedAt?: Date | string
  /** Render only the phase spine (no chat header, "Using" chips, or working word) for embedding in a panel. */
  embedded?: boolean
}

/** Sub-second timings carry no signal to a human, so don't show them. */
const MIN_SHOWN_MS = 800

const toMs = (ts: Date | string): number => new Date(ts).getTime()

/**
 * Formats an elapsed duration: one-decimal seconds under a minute
 * (e.g. 1500ms -> "1.5s"), minutes + seconds above (e.g. 85400ms -> "1m 25s").
 */
const formatDuration = (ms: number): string => {
  const seconds = Math.max(0, ms) / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

const formatResponseDuration = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const seconds = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  if (totalMinutes < 60) return `${totalMinutes}:${seconds.toString().padStart(2, '0')}`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

/**
 * Whimsical present-participles cycled in the working header while the agent
 * runs. Index 0 ("Thinking") is the deterministic first word; the rest flip in
 * at random with a soft transition.
 */
const THINKING_WORDS = [
  'Thinking',
  'Cooking',
  'Contemplating',
  'Understanding',
  'Reasoning',
  'Pondering',
  'Analyzing',
  'Synthesizing',
  'Computing',
  'Reflecting',
  'Considering',
  'Exploring',
  'Investigating',
  'Connecting',
  'Digging in',
  'Crunching',
  'Assembling',
  'Formulating',
  'Deliberating',
  'Mulling',
  'Processing',
  'Inferring',
  'Deducing',
  'Calculating',
  'Wondering',
  'Brewing',
  'Percolating',
  'Noodling',
  'Untangling',
  'Parsing',
  'Distilling',
  'Weighing',
  'Sketching',
  'Drafting',
  'Piecing it together',
  'Mapping',
  'Scanning',
  'Sifting',
  'Gathering',
  'Tinkering',
  'Strategizing',
  'Theorizing',
  'Hypothesizing',
  'Examining',
  'Evaluating',
  'Ruminating',
  'Cogitating',
  'Marinating',
  'Orchestrating',
  'Puzzling',
]

interface Phase {
  head: ThinkingStep
  children: ThinkingStep[]
  reasoning?: string
  reflection?: string
  explanation?: string
  key: string
}

const TOOL_MSG_RE =
  /content=(["'])([\s\S]*?)\1\s+name=(["'])[\s\S]*?\3(?:\s+tool_call_id=(["'])[\s\S]*?\4)?/g

export const cleanToolNoise = (text: string): string =>
  (text || '').replace(TOOL_MSG_RE, (_full, _q, content) => content).trim()

export const foldedStepText = (step: ThinkingStep): string =>
  cleanToolNoise(extractFoldedOutput(step.content || ''))

const stripReasoningLabel = (text: string): string =>
  text.replace(/^\s*reasoning\b[:\s]*/i, '').trimStart()

/**
 * A single tool call can surface more than once in the stream: a nested
 * announcement under its agent, the top-level execution, a function-group echo,
 * or a mid-run repaint before the result lands. Collapse those into one row.
 *
 * Only known tools are deduped, and only within the same tool label + input
 * summary: the announcements drop once any execution lands, while genuinely
 * different calls are kept because they differ by input summary. Non-tool rows
 * (agents, model/LLM, reasoning) always pass through unchanged. When several
 * copies describe the same call, the one kept is the top-level execution, then a
 * completed one, then the latest.
 */
export const dedupeNestedToolSteps = (steps: ThinkingStep[]): ThinkingStep[] => {
  // Step 1: drop nested steps that duplicate a top-level call by tool label AND
  // input summary, and lift a nested input summary onto a top-level call that
  // carries none. A distinct nested call differs by its input summary and is kept.
  const labelOf = (s: ThinkingStep): string => getToolLabel(s.functionName).label
  const topLevelKeys = new Set<string>()
  const topLevelLabelsMissingSummary = new Set<string>()
  for (const s of steps) {
    if (!s.isTopLevel) continue
    topLevelKeys.add(`${labelOf(s)}\u0000${s.argSummary ?? ''}`)
    if (!s.argSummary) topLevelLabelsMissingSummary.add(labelOf(s))
  }
  const nestedSummaries = new Map<string, string>()
  for (const step of steps) {
    if (step.isTopLevel || !step.argSummary) continue
    const label = labelOf(step)
    const existing = nestedSummaries.get(label)
    if (!existing || step.argSummary.length > existing.length) {
      nestedSummaries.set(label, step.argSummary)
    }
  }
  const isNestedDuplicate = (s: ThinkingStep): boolean =>
    topLevelKeys.has(`${labelOf(s)}\u0000${s.argSummary ?? ''}`) ||
    topLevelLabelsMissingSummary.has(labelOf(s))
  const enriched = steps
    .filter((s) => s.isTopLevel || !isNestedDuplicate(s))
    .map((step) => {
      if (!step.isTopLevel || step.argSummary) return step
      const nestedSummary = nestedSummaries.get(labelOf(step))
      return nestedSummary ? { ...step, argSummary: nestedSummary } : step
    })

  // Step 2: collapse remaining duplicate tool rows within the same tool label +
  // input summary, keeping the top-level / completed copy.
  const rank = (s: ThinkingStep, index: number): [number, number, number] => [
    s.isTopLevel ? 1 : 0,
    s.status === 'success' || s.isComplete ? 1 : 0,
    index,
  ]
  const rankIsHigher = (a: [number, number, number], b: [number, number, number]): boolean =>
    a[0] !== b[0] ? a[0] > b[0] : a[1] !== b[1] ? a[1] > b[1] : a[2] > b[2]

  const groups = new Map<string, number[]>()
  enriched.forEach((s, i) => {
    if (!isKnownTool(s.functionName)) return
    const key = `${getToolLabel(s.functionName).label}\u0000${s.argSummary ?? ''}`
    const arr = groups.get(key)
    if (arr) arr.push(i)
    else groups.set(key, [i])
  })

  const drop = new Set<number>()
  for (const indices of groups.values()) {
    if (indices.length < 2) continue
    let best = indices[0]
    for (const i of indices)
      if (rankIsHigher(rank(enriched[i], i), rank(enriched[best], best))) best = i
    for (const i of indices) if (i !== best) drop.add(i)
  }

  return enriched.filter((_, i) => !drop.has(i))
}

/**
 * Folds the flat step stream into phases using the `isTopLevel` flag:
 * top-level steps are phase heads; everything else nests under the most recent
 * phase. Reasoning / reflection / explanation notes fold into their phase rather
 * than becoming rows of their own. When no step is flagged top-level (legacy /
 * restored sessions, tests), every step becomes its own phase, i.e. it degrades
 * gracefully to a flat list.
 */
export const buildPhases = (steps: ThinkingStep[]): Phase[] => {
  const isFolded = (s: ThinkingStep) => isFoldedTextStep(s.functionName)
  const hasTopLevel = steps.some((s) => s.isTopLevel && !isFolded(s))
  const phases: Phase[] = []

  const foldInto = (key: 'reasoning' | 'reflection' | 'explanation', text: string) => {
    if (!text || phases.length === 0) return
    const current = phases[phases.length - 1]
    current[key] = current[key] ? `${current[key]}\n\n${text}` : text
  }

  for (const step of steps) {
    if (isReasoningStep(step.functionName)) {
      foldInto('reasoning', stripReasoningLabel(foldedStepText(step)))
      continue
    }
    if (isReflectionStep(step.functionName)) {
      // Latest note wins for the phase (a retry note during the call, then the post-result note);
      // notes never accumulate, and each note folds into the phase whose tool it describes.
      const text = foldedStepText(step)
      if (text && phases.length > 0) {
        const phase = phases[phases.length - 1]
        phase.reflection = text
        if (phase.children.length > 0 && isLLMModel(phase.children.at(-1)!.functionName)) {
          phase.children.pop()
        }
      }
      continue
    }
    if (isExplanationStep(step.functionName)) {
      foldInto('explanation', foldedStepText(step))
      continue
    }
    if (!hasTopLevel || step.isTopLevel || phases.length === 0) {
      phases.push({ head: step, children: [], key: step.id })
    } else {
      phases[phases.length - 1].children.push(step)
    }
  }
  return phases
}

const SourceChip: FC<{ kind: SourceKind; label: string }> = ({ kind, label }) => (
  <span className="thinking-source-pill text-success inline-flex items-center gap-1 rounded-full border px-2 py-0.5">
    <SourceKindIcon kind={kind} />
    <Text kind="label/regular/xs" className="text-success max-w-[150px] truncate">
      {label}
    </Text>
  </span>
)

/**
 * The working label: a subtle, gray status word that flips to a new random word
 * every couple seconds with a soft vertical transition. Starts on "Thinking".
 */
const ThinkingWord: FC = () => {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setIndex((prev) => {
        let next = prev
        while (next === prev) next = Math.floor(Math.random() * THINKING_WORDS.length)
        return next
      })
    }, 2200)
    return () => clearInterval(id)
  }, [])

  return (
    <span className="thinking-word text-subtle inline-flex items-baseline">
      <span className="inline-flex overflow-hidden">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={index}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            {THINKING_WORDS[index]}
          </motion.span>
        </AnimatePresence>
      </span>
      <span className="thinking-dots" aria-hidden="true">
        <span>.</span>
        <span>.</span>
        <span>.</span>
      </span>
    </span>
  )
}

/** Lifecycle state of a child sub-call, given whether the parent phase is done. */
const childState = (child: ThinkingStep, isLastInRunningPhase: boolean): NodeState => {
  if (child.status === 'error') return 'error'
  if (child.status === 'success' || child.isComplete) return 'done'
  return isLastInRunningPhase ? 'running' : 'done'
}

const CollapsibleText: FC<{
  label: string
  text: string
  defaultOpen: boolean
  live?: boolean
  markdown?: boolean
}> = ({ label, text, defaultOpen, live = false, markdown = false }) => {
  const [open, setOpen] = useState(defaultOpen)
  const userToggledRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentId = useId()

  useEffect(() => {
    if (userToggledRef.current) return
    setOpen(defaultOpen)
  }, [defaultOpen])

  useEffect(() => {
    if (!open || !live) return
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    if (nearBottom) el.scrollTop = el.scrollHeight
  }, [text, open, live])

  const toggle = (): void => {
    userToggledRef.current = true
    setOpen((v) => !v)
  }

  return (
    <div className="thinking-reasoning">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={contentId}
        className="thinking-reasoning-toggle"
      >
        <Text kind="label/regular/xs" className="thinking-reasoning-label">
          {open ? `Hide ${label.toLowerCase()}` : label}
        </Text>
        <AnimatedChevron />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={contentId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div
              ref={scrollRef}
              className={cn(
                'thinking-reasoning-scroll',
                markdown && 'thinking-reasoning-scroll-tall'
              )}
            >
              {markdown ? (
                <MarkdownRenderer content={text} compact className="thinking-reasoning-text" />
              ) : (
                <p className="thinking-reasoning-text">{text}</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/**
 * One phase in the timeline: a head row (status + tool label + input summary),
 * with its model / tool sub-calls collapsible underneath.
 */
const PhaseRow: FC<{
  phase: Phase
  state: NodeState
  duration: string | null
  defaultOpen: boolean
  isActive: boolean
  index: number
}> = ({ phase, state, duration, defaultOpen, isActive, index }) => {
  const [open, setOpen] = useState(defaultOpen)
  const userToggledRef = useRef(false)
  const substepsId = useId()
  const childCount = phase.children.length
  const hasChildren = childCount > 0
  const reflectionNote = phase.reflection

  useEffect(() => {
    if (userToggledRef.current) return
    setOpen(defaultOpen)
  }, [defaultOpen])

  const headInner: ReactNode = (
    <>
      <div className="min-w-0">
        <ToolCallRow name={phase.head.functionName} status={state} args={phase.head.argSummary} />
      </div>
      <Flex align="center" gap="2" className="shrink-0">
        {hasChildren && (
          <span className="thinking-substep-toggle">
            {open ? 'Hide' : `${childCount} call${childCount === 1 ? '' : 's'}`}
            <AnimatedChevron />
          </span>
        )}
        {duration && (
          <Text kind="body/regular/xs" className="thinking-phase-meta tabular-nums">
            {duration}
          </Text>
        )}
      </Flex>
    </>
  )

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        type: 'spring',
        stiffness: 480,
        damping: 34,
        delay: Math.min(index * 0.04, 0.25),
      }}
      className={cn('thinking-phase relative', `is-${state}`)}
    >
      {hasChildren ? (
        <button
          type="button"
          onClick={() => {
            userToggledRef.current = true
            setOpen((v) => !v)
          }}
          aria-expanded={open}
          aria-controls={substepsId}
          className="thinking-phase-head"
        >
          {headInner}
        </button>
      ) : (
        <div className="thinking-phase-head">{headInner}</div>
      )}

      {phase.reasoning && (
        <CollapsibleText label="Reasoning" text={phase.reasoning} defaultOpen={false} live={isActive} />
      )}

      {phase.explanation && (
        <CollapsibleText label="Explanation" text={phase.explanation} defaultOpen markdown />
      )}

      {reflectionNote && (
        <p className="thinking-reasoning-text thinking-reflection-note">{reflectionNote}</p>
      )}

      {isActive && <span className="thinking-progress" aria-hidden="true" />}

      <AnimatePresence initial={false}>
        {open && hasChildren && (
          <motion.ul
            id={substepsId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="thinking-substeps overflow-hidden"
          >
            {phase.children.map((child, childIndex) => (
              <li key={child.id} className="thinking-substep">
                <ToolCallRow
                  name={child.functionName}
                  status={childState(child, state === 'running' && childIndex === childCount - 1)}
                  args={child.argSummary}
                  size="xs"
                />
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

/**
 * Generic tokens that recur across unrelated tool and source names, so they
 * carry no source-identity signal and are ignored when matching a tool to a
 * configured source.
 */
const GENERIC_SOURCE_TOKENS = new Set([
  'tool',
  'tools',
  'search',
  'retrieval',
  'retrieve',
  'layer',
  'agent',
  'api',
  'mcp',
  'query',
  'lookup',
  'fetch',
  'get',
  'advanced',
])

const sourceTokens = (value: string): Set<string> =>
  new Set(
    (value || '')
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((token) => token.length > 0 && !GENERIC_SOURCE_TOKENS.has(token))
  )

/**
 * Best-effort, dynamic match of a tool/step function name to a configured data
 * source id. The frontend never receives the backend's authoritative
 * tool->source map (see the backend data_source_registry), so a tool is
 * attributed to a source when its function name contains the source id or shares
 * a meaningful (non-generic) token with it. This resolves ANY user-configured
 * source whose tools are named after it (`confluence_search` -> `confluence`,
 * `web_search_tool` -> `web_search`, `knowledge_retrieval` -> `knowledge_layer`,
 * `eci__gdrive` -> `gdrive`) rather than a fixed set of sources.
 */
const toolMatchesSource = (functionName: string, sourceId: string): boolean => {
  const name = (functionName || '').toLowerCase().replace(/^tool:\s*/, '')
  const id = sourceId.toLowerCase()
  if (!name || !id) return false
  if (name.includes(id) || id.includes(name)) return true
  const nameTokens = sourceTokens(name)
  if (nameTokens.size === 0) return false
  for (const token of sourceTokens(id)) {
    if (nameTokens.has(token)) return true
  }
  return false
}

/**
 * Live, phased progress timeline for the agent's intermediate steps.
 */
export const ChatThinking: FC<ChatThinkingProps> = ({
  steps,
  isThinking = true,
  isInterrupted = false,
  isWaiting = false,
  enabledDataSources = [],
  messageFiles = [],
  responseStartedAt,
  responseCompletedAt,
  embedded = false,
}) => {
  const [open, setOpen] = useState(isThinking || isWaiting)
  const [now, setNow] = useState(() => Date.now())
  const [stoppedAt, setStoppedAt] = useState<number | null>(null)
  const [responseNow, setResponseNow] = useState(() => Date.now())
  const wasThinkingRef = useRef(isThinking)

  useEffect(() => {
    setOpen(isThinking || isWaiting)
  }, [isThinking, isWaiting])

  useEffect(() => {
    if (isThinking) {
      wasThinkingRef.current = true
      setStoppedAt(null)
      setNow(Date.now())
      const id = setInterval(() => setNow(Date.now()), 100)
      return () => clearInterval(id)
    }
    if (wasThinkingRef.current) {
      wasThinkingRef.current = false
      setStoppedAt(Date.now())
    }
  }, [isThinking])

  useEffect(() => {
    if (responseCompletedAt) {
      setResponseNow(toMs(responseCompletedAt))
      return
    }
    if (!isThinking && !isWaiting) return
    setResponseNow(Date.now())
    const id = setInterval(() => setResponseNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [isThinking, isWaiting, responseCompletedAt])

  // Hide internal wrapper nodes (e.g. "<workflow>") -- they carry no signal to a user.
  const visibleSteps = useMemo(
    () =>
      dedupeNestedToolSteps(
        steps.filter(
          (s) =>
            !/^<.*>$/.test(s.functionName) &&
            // Keep agent phases, but never mount their implementation-detail LLM calls.
            !(!s.isTopLevel && isLLMModel(s.functionName))
        )
      ),
    [steps]
  )
  const phases = useMemo(() => buildPhases(visibleSteps), [visibleSteps])
  const realSteps = useMemo(
    () => visibleSteps.filter((s) => !isFoldedTextStep(s.functionName)),
    [visibleSteps]
  )

  const lastStepEnd = useMemo(() => {
    let end = 0
    for (const step of steps) {
      const ts = step.completedAt ?? step.timestamp
      if (!ts) continue
      const ms = toMs(ts)
      if (ms > end) end = ms
    }
    return end > 0 ? end : null
  }, [steps])

  const usedSources = useMemo(
    () =>
      enabledDataSources.filter(
        (source) =>
          source !== 'knowledge_layer' &&
          visibleSteps.some((step) => toolMatchesSource(step.functionName, source))
      ),
    [visibleSteps, enabledDataSources]
  )
  const hasDataSources = usedSources.length > 0
  const hasFiles = messageFiles.length > 0

  if (realSteps.length === 0 && !hasDataSources && !hasFiles) {
    return null
  }

  const statusLabel = isWaiting ? 'Needs your input' : isInterrupted ? 'Interrupted' : 'Done'
  const stepCount = phases.length
  const stepCountLabel = `${stepCount} step${stepCount === 1 ? '' : 's'}`
  const responseEnd = responseCompletedAt
    ? toMs(responseCompletedAt)
    : isThinking || isWaiting
      ? responseNow
      : lastStepEnd
  const responseDuration =
    responseStartedAt != null && responseEnd != null
      ? formatResponseDuration(responseEnd - toMs(responseStartedAt))
      : null

  const hasTools = hasDataSources || hasFiles
  const showHeaderTools = !isThinking && !isWaiting && !isInterrupted && hasTools

  const sourceChips = (
    <>
      {usedSources.map((id) => (
        <SourceChip key={id} kind={getDataSourceKind(id)} label={getDataSourceLabel(id)} />
      ))}
      {messageFiles.map((file) => (
        <SourceChip key={file.id} kind="doc" label={file.fileName} />
      ))}
    </>
  )

  /**
   * Lifecycle state of phase `index`.
   *
   * Status comes from the step's own `status` (success -> done, error -> error,
   * running -> running), not its position. A phase is treated as complete when
   * either its head reports completion OR a later phase has started (implicit
   * completion), so middle phases never get stuck pending. Only the last,
   * still-incomplete phase shows the live working / waiting / interrupted state.
   */
  const phaseStateOf = (phase: Phase, index: number): NodeState => {
    if (phase.head.status === 'error') return 'error'

    const headDone = phase.head.status === 'success' || phase.head.isComplete
    const laterStarted = index < phases.length - 1
    if (headDone || laterStarted) return 'done'

    if (isThinking) return 'running'
    if (isWaiting) return 'waiting'
    if (isInterrupted) return 'interrupted'
    return 'done'
  }

  const phaseEnd = (phase: Phase, index: number): number => {
    const start = toMs(phase.head.timestamp)
    if (phase.head.completedAt) return toMs(phase.head.completedAt)
    if (index < phases.length - 1) return toMs(phases[index + 1].head.timestamp)
    if (isThinking) return now
    if (stoppedAt !== null) return stoppedAt
    const lastChild = phase.children.at(-1)
    if (lastChild?.completedAt) return toMs(lastChild.completedAt)
    if (lastChild) return toMs(lastChild.timestamp)
    return start
  }

  const phaseDuration = (phase: Phase, index: number): string | null => {
    const ms = phaseEnd(phase, index) - toMs(phase.head.timestamp)
    return ms >= MIN_SHOWN_MS ? formatDuration(ms) : null
  }

  const traceList = (
    <div className="relative mt-1 py-1.5 pr-1">
      <span
        aria-hidden="true"
        className="thinking-trace-rail absolute bottom-2 left-[9px] top-2 w-[2px] rounded-full"
      />
      <ol className="relative" role="list" aria-label="Thinking steps">
        <AnimatePresence initial={false}>
          {phases.map((phase, index) => {
            const state = phaseStateOf(phase, index)
            return (
              <PhaseRow
                key={phase.key}
                index={index}
                phase={phase}
                state={state}
                duration={phaseDuration(phase, index)}
                defaultOpen={embedded || state === 'running'}
                isActive={state === 'running'}
              />
            )
          })}
        </AnimatePresence>
      </ol>
    </div>
  )

  if (embedded) {
    return phases.length > 0 ? <div className="w-full py-1">{traceList}</div> : null
  }

  return (
    <div className="w-full py-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group flex w-full items-center justify-between rounded-[var(--radius-card)] py-1.5 text-left transition-colors"
      >
        <Flex align="center" gap={isThinking ? '4' : '2'} className="min-w-0">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full">
            {isThinking ? (
              <Spinner size="small" aria-label="Working" />
            ) : isWaiting ? (
              <Clock className="text-secondary h-4 w-4" />
            ) : isInterrupted ? (
              <Warning className="text-warning h-4 w-4" />
            ) : (
              <CheckCircle className="text-success h-4 w-4" />
            )}
          </span>
          {isThinking ? (
            <ThinkingWord />
          ) : showHeaderTools ? (
            <Flex align="center" gap="2" className="min-w-0 flex-wrap">
              <Text kind="label/semibold/md" className="mono-label">
                Using
              </Text>
              {sourceChips}
            </Flex>
          ) : (
            <Text kind="label/semibold/md" className="text-primary truncate">
              {statusLabel}
            </Text>
          )}
        </Flex>
        {phases.length > 0 && (
          <Flex
            align="center"
            gap="2.5"
            className="text-secondary hover:text-primary shrink-0 transition-colors"
          >
            {responseDuration && (
              <span className="flex shrink-0 items-center gap-1" aria-label="Total response time">
                <Clock className="text-subtle h-3.5 w-3.5" />
                <Text kind="label/regular/sm" className="mono-meta text-secondary tabular-nums">
                  {responseDuration}
                </Text>
              </span>
            )}
            {responseDuration && (
              <span aria-hidden="true" className="bg-base h-3.5 w-px" />
            )}
            <Flex align="center" gap="1" className="pl-0.5">
              <Text
                kind="label/regular/sm"
                className="mono-meta text-secondary group-hover:text-primary"
              >
                {open ? 'Hide steps' : stepCountLabel}
              </Text>
              <AnimatedChevron />
            </Flex>
          </Flex>
        )}
      </button>

      <AnimatePresence initial={false}>
        {open && phases.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            {traceList}
          </motion.div>
        )}
      </AnimatePresence>

      {hasTools && !showHeaderTools && (
        <Flex align="center" gap="2" className="mt-2 flex-wrap pl-2">
          <Text kind="label/semibold/md" className="mono-label">
            Using
          </Text>
          {sourceChips}
        </Flex>
      )}
    </div>
  )
}
