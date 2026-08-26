// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentPrompt Component
 *
 * Displays prompts from the agent that require user response.
 *
 * For plan approval prompts, inline Approve/Reject buttons are rendered
 * inside the block so the user can respond without typing.
 *
 * The whole prompt renders through the shared CollapsibleBlock so it reads
 * uniform with the inline thinking block. While the prompt still needs the user
 * the block stays expanded and is not collapsible (the user has to act); the
 * moment the plan is approved or rejected the entire block auto-collapses to a
 * small header (status glyph + label + a compact decision summary), re-openable
 * on click.
 */

'use client'

import { type FC, type KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Flex, Text, Button } from '@/adapters/ui'
import { Clock, CheckCircle, Close, Paperplane } from '@/adapters/ui/icons'
import { CollapsibleBlock } from '@/shared/components/CollapsibleBlock'
import { MarkdownRenderer } from '@/shared/components/MarkdownRenderer'
import { cn } from '@/shared/lib/cn'
import { useChatStore } from '../store'
import type { PromptType } from '../types'

export type { PromptType }

const APPROVAL_PROMPT_RE =
  /Reply\s+\*{0,2}approve\*{0,2}\s+to proceed,\s+\*{0,2}reject\*{0,2}\s+to cancel/i

const CLARIFIER_CANCEL_REPLY = '__USER_CANCELLED__'

const NUMBERED_LINE_RE = /^\s*(\d+)[.)]\s+(.+?)\s*$/
const TITLE_LINE_RE = /^\s*\*{0,2}Title:\*{0,2}\s*(.+?)\s*$/i
const SECTIONS_LINE_RE = /^\s*\*{0,2}Sections:\*{0,2}\s*$/i

const plainOptionLabel = (value: string): string =>
  value
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')

interface PlanPreviewData {
  title?: string
  sections: string[]
  fallback: string
}

/**
 * Splits a clarifier's markdown into the intro text and any embedded numbered
 * choices (e.g. "1. Last 12 months"), so the choices can render as selectable
 * cards instead of plain text.
 */
function parseNumberedChoices(content: string): { intro: string; choices: string[] } {
  const lines = content.split('\n')
  const choices: string[] = []
  let firstIdx = -1
  lines.forEach((line, i) => {
    const match = line.match(NUMBERED_LINE_RE)
    if (match) {
      if (firstIdx === -1) firstIdx = i
      choices.push(match[2].trim())
    }
  })
  const intro = firstIdx === -1 ? content : lines.slice(0, firstIdx).join('\n').trim()
  return { intro, choices }
}

function parsePlanPreview(content: string): PlanPreviewData {
  const lines = content.split('\n').filter((line) => !APPROVAL_PROMPT_RE.test(line))

  let title: string | undefined
  let sectionsStart = -1
  const sections: string[] = []

  lines.forEach((line, index) => {
    const titleMatch = line.match(TITLE_LINE_RE)
    if (titleMatch) {
      title = titleMatch[1].trim()
      return
    }
    if (SECTIONS_LINE_RE.test(line)) {
      sectionsStart = index
    }
  })

  if (sectionsStart >= 0) {
    lines.slice(sectionsStart + 1).forEach((line) => {
      const match = line.match(NUMBERED_LINE_RE)
      if (match) sections.push(match[2].trim())
    })
  }

  return {
    title,
    sections,
    fallback: lines.join('\n').trim(),
  }
}

export interface AgentPromptProps {
  /** Unique identifier for this prompt */
  id: string
  /** Backend interaction id this prompt answers; gates the live controls to the current pending interaction. */
  interactionId?: string
  /** Type of prompt */
  type: PromptType
  /** Main content/question from the agent */
  content: string
  /** Options for choice prompts (displayed as list) */
  options?: string[]
  /** Placeholder text for text input prompts (not used - display only) */
  placeholder?: string
  /** Whether the prompt has been responded to */
  isResponded?: boolean
  /** The user's response (if already responded) */
  response?: string
  /** Callback when user responds (not used - display only) */
  onRespond?: (promptId: string, response: string) => void
  /** Timestamp retained for backward-compatible callers; prompts do not render wall-clock time. */
  timestamp?: Date | string
  /** Rendering mode. Inline mode is used inside the unified assistant turn lane. */
  variant?: 'default' | 'inline'
}

/**
 * Interactive agent prompt block.
 *
 * The user can respond right inside the block: choice prompts render selectable
 * option buttons, free-text clarifications render a small inline chat input, and
 * plan-approval prompts render Approve/Reject buttons. The main chat input still
 * works as a fallback. When not yet respondable (no interaction handler) the
 * options fall back to a read-only list.
 *
 * The block is driven by the shared CollapsibleBlock: it is locked open (not
 * collapsible) while it needs the user, and auto-collapses to its header once a
 * response has been given.
 */
export const AgentPrompt: FC<AgentPromptProps> = ({
  interactionId,
  type,
  content,
  options = [],
  isResponded = false,
  response,
  variant = 'default',
}) => {
  const respondToInteractionFn = useChatStore((state) => state.respondToInteractionFn)
  const pendingInteraction = useChatStore((state) => state.pendingInteraction)
  const isApprovalPrompt =
    type === 'approval' || type === 'plan_approval' || APPROVAL_PROMPT_RE.test(content)
  const isForeignInteraction =
    !!interactionId && !!pendingInteraction && pendingInteraction.id !== interactionId
  const canRespond = !isResponded && !!respondToInteractionFn && !isForeignInteraction
  const showApprovalButtons = isApprovalPrompt && canRespond

  const respond = useCallback(
    (value: string) => {
      const trimmed = value.trim()
      if (!trimmed) return
      respondToInteractionFn?.(trimmed)
    },
    [respondToInteractionFn]
  )

  const handleApprove = useCallback(() => {
    respondToInteractionFn?.('approve')
  }, [respondToInteractionFn])

  const handleReject = useCallback(() => {
    respondToInteractionFn?.('reject')
  }, [respondToInteractionFn])

  const handleCancel = useCallback(() => {
    respondToInteractionFn?.(CLARIFIER_CANCEL_REPLY)
  }, [respondToInteractionFn])

  const hasPropOptions = !isApprovalPrompt && options.length > 0
  const parsed = hasPropOptions || isApprovalPrompt ? null : parseNumberedChoices(content)
  const hasParsedChoices = !!parsed && parsed.choices.length >= 2
  const choiceItems: { label: string; value: string }[] = hasPropOptions
    ? options.map((label) => ({ label, value: label }))
    : hasParsedChoices
      ? parsed!.choices.map((label, index) => ({ label, value: String(index + 1) }))
      : []
  const displayContent = hasParsedChoices ? parsed!.intro : content
  const displayResponse =
    response === CLARIFIER_CANCEL_REPLY
      ? 'Cancelled'
      : response && choiceItems.length > 0
        ? (choiceItems.find((choice) => choice.value === response)?.label ?? response)
        : response

  const approvalDecision: 'approve' | 'reject' | null =
    isApprovalPrompt && response ? (/reject/i.test(response) ? 'reject' : 'approve') : null
  const approved = approvalDecision === 'approve'

  const choiceItemsRef = useRef(choiceItems)
  choiceItemsRef.current = choiceItems

  useEffect(() => {
    if (!canRespond) return
    const isTyping = (): boolean => {
      const el = document.activeElement
      return (
        el instanceof HTMLElement &&
        (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
      )
    }
    const onKeyDown = (e: globalThis.KeyboardEvent): void => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping()) return
      if (showApprovalButtons) {
        if (e.key === 'Enter') {
          const target = e.target
          if (
            target instanceof HTMLElement &&
            target.closest('button, a, [role="button"], [role="link"]')
          ) {
            return
          }
          e.preventDefault()
          handleApprove()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          handleReject()
        }
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        handleCancel()
        return
      }
      const items = choiceItemsRef.current
      if (items.length > 0 && /^[1-9]$/.test(e.key)) {
        const index = Number(e.key) - 1
        if (index < items.length) {
          e.preventDefault()
          respond(items[index].value)
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [canRespond, showApprovalButtons, respond, handleApprove, handleReject, handleCancel])

  /**
   * The whole block collapses only after a response. It opens by default while
   * waiting and snaps shut the instant `isResponded` flips true, mirroring the
   * thinking block's expanded-while-working / collapsed-when-done behaviour.
   */
  const [open, setOpen] = useState(!isResponded)
  useEffect(() => {
    setOpen(!isResponded)
  }, [isResponded])

  const headerTitle = (
    <Text
      kind="label/semibold/sm"
      className={cn('mono-label', isResponded ? 'text-secondary' : 'text-primary')}
    >
      {isResponded ? 'Input received' : 'Needs your input'}
    </Text>
  )

  const decisionSummary = isApprovalPrompt
    ? approvalDecision === 'approve'
      ? 'Plan approved'
      : approvalDecision === 'reject'
        ? 'Plan rejected'
        : null
    : (displayResponse ?? null)

  const headerMeta =
    isResponded && decisionSummary ? (
      isApprovalPrompt ? (
        <Text kind="label/regular/sm" className="text-subtle max-w-[220px] truncate">
          {decisionSummary}
        </Text>
      ) : (
        <MarkdownRenderer
          content={decisionSummary}
          compact
          className="text-subtle max-w-[220px] [&_p]:m-0 [&_p]:truncate [&_p]:text-sm"
        />
      )
    ) : null

  const block = (
    <CollapsibleBlock
      icon={
        isResponded ? (
          <CheckCircle className="text-success h-4 w-4" />
        ) : (
          <Clock className="text-brand h-4 w-4" />
        )
      }
      title={headerTitle}
      meta={headerMeta}
      open={open}
      onOpenChange={setOpen}
      collapsible={isResponded}
    >
      <Flex direction="col" gap="3" className="pl-9 pr-1 pt-1">
        {isApprovalPrompt ? (
          <PlanPreview content={content} isResponded={isResponded} />
        ) : (
          <div className={cn('prose prose-sm max-w-none', isResponded && 'opacity-70')}>
            <MarkdownRenderer content={displayContent} />
          </div>
        )}

        {choiceItems.length > 0 &&
          !isResponded &&
          (canRespond ? (
            <Flex direction="col" gap="1.5">
              <SelectableOptions items={choiceItems} onSelect={respond} />
              <Text kind="label/regular/sm" className="agent-key-hint">
                Press 1 to {choiceItems.length} to choose
              </Text>
            </Flex>
          ) : (
            <OptionsList options={choiceItems.map((choice) => choice.label)} />
          ))}

        {!isApprovalPrompt && canRespond && (
          <>
            {choiceItems.length > 0 && (
              <div className="agent-divider">Or describe it yourself</div>
            )}
            <InlineResponseInput onSubmit={respond} />
            <Flex align="center" justify="between" gap="2">
              <Text kind="label/regular/sm" className="agent-key-hint">
                <span className="agent-key-cap">Esc</span> Cancel
              </Text>
              <Button
                kind="secondary"
                size="small"
                onClick={handleCancel}
                aria-label="Cancel request"
                className="agent-action-reject"
              >
                Cancel request
              </Button>
            </Flex>
          </>
        )}

        {showApprovalButtons && (
          <div className="agent-plan-actions">
            <Text kind="label/regular/sm" className="agent-key-hint">
              <span className="agent-key-cap">Enter</span> Approve&nbsp;&middot;&nbsp;
              <span className="agent-key-cap">Esc</span> Reject
            </Text>
            <Flex gap="2">
              <Button
                kind="primary"
                size="small"
                onClick={handleApprove}
                aria-label="Approve plan"
                className="agent-action-approve"
              >
                Approve
              </Button>
              <Button
                kind="secondary"
                size="small"
                onClick={handleReject}
                aria-label="Reject plan"
                className="agent-action-reject"
              >
                Reject
              </Button>
            </Flex>
          </div>
        )}

        {isResponded &&
          (isApprovalPrompt ? (
            approvalDecision ? (
              <ApprovalReceipt approved={approved} />
            ) : null
          ) : (
            <ResponseDisplay response={displayResponse} />
          ))}
      </Flex>
    </CollapsibleBlock>
  )

  const promptCard = (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
      className={cn('flex w-full flex-col', variant === 'default' && 'max-w-[85%]')}
    >
      {block}
    </motion.div>
  )

  if (variant === 'inline') {
    return promptCard
  }

  return (
    <Flex justify="start" className="w-full">
      {promptCard}
    </Flex>
  )
}

/**
 * Renders the parsed research plan (kicker + title + numbered sections). Collapse
 * of the plan is owned by the surrounding CollapsibleBlock, so this always shows
 * its body and keeps the "Research Plan Preview" kicker.
 */
const PlanPreview: FC<{ content: string; isResponded: boolean }> = ({ content, isResponded }) => {
  const plan = parsePlanPreview(content)
  const hasStructuredPlan = !!plan.title || plan.sections.length > 0

  if (!hasStructuredPlan) {
    return (
      <div className={cn('prose prose-sm max-w-none', isResponded && 'opacity-70')}>
        <MarkdownRenderer content={plan.fallback} />
      </div>
    )
  }

  const sectionCount = plan.sections.length
  const countLabel =
    sectionCount > 0 ? `${sectionCount} section${sectionCount === 1 ? '' : 's'}` : null

  return (
    <section className="agent-plan-preview">
      <Flex align="center" gap="2" className="mb-3">
        <span className="agent-plan-kicker" aria-hidden="true" />
        <Text kind="label/semibold/sm" className="text-brand font-mono uppercase tracking-[0.12em]">
          Research Plan Preview
        </Text>
        {countLabel && <span className="agent-plan-count">{countLabel}</span>}
      </Flex>

      {plan.title && (
        <div className="agent-plan-title">
          <MarkdownRenderer
            content={plan.title}
            compact
            className="agent-plan-title-text min-w-0 flex-1"
          />
        </div>
      )}

      {plan.sections.length > 0 && (
        <ol className="agent-plan-sections" aria-label="Research plan sections">
          {plan.sections.map((section, index) => (
            <motion.li
              key={`${index}-${section}`}
              className="agent-plan-section"
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                duration: 0.22,
                ease: [0.22, 1, 0.36, 1],
                delay: Math.min(index * 0.04, 0.3),
              }}
            >
              <span className="agent-plan-section-index">
                {String(index + 1).padStart(2, '0')}
              </span>
              <MarkdownRenderer
                content={section}
                compact
                className="text-primary min-w-0 flex-1 [&_p]:text-sm"
              />
            </motion.li>
          ))}
        </ol>
      )}
    </section>
  )
}

/**
 * Selectable choice options: clicking one responds to the agent immediately.
 */
const SelectableOptions: FC<{
  items: { label: string; value: string }[]
  onSelect: (value: string) => void
}> = ({ items, onSelect }) => {
  return (
    <Flex direction="col" gap="1.5">
      {items.map((item, index) => (
        <button
          key={index}
          type="button"
          onClick={() => onSelect(item.value)}
          aria-label={`Choose: ${plainOptionLabel(item.label)}`}
          className="agent-option-button focus-visible:ring-brand flex items-center gap-2.5 rounded-[var(--radius-card)] border p-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2"
        >
          <span className="agent-option-index">{index + 1}</span>
          <MarkdownRenderer
            content={item.label}
            compact
            className="text-primary min-w-0 flex-1 [&_p]:text-sm"
          />
        </button>
      ))}
    </Flex>
  )
}

/**
 * Compact inline chat input rendered inside the block for free-text responses.
 */
const InlineResponseInput: FC<{ onSubmit: (value: string) => void }> = ({ onSubmit }) => {
  const [value, setValue] = useState('')

  const submit = (): void => {
    const trimmed = value.trim()
    if (!trimmed) return
    onSubmit(trimmed)
    setValue('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
  }

  return (
    <Flex
      align="center"
      gap="2"
      className="brand-focus-glow ai-soft-panel rounded-[var(--radius-card)] border p-1.5 pl-3"
    >
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type your response..."
        aria-label="Respond to the agent"
        className="text-primary placeholder:text-subtle min-w-0 flex-1 bg-transparent text-sm outline-none"
      />
      <Button
        kind="primary"
        size="small"
        onClick={submit}
        disabled={!value.trim()}
        aria-label="Send response"
        title="Send response"
      >
        <Paperplane className="h-4 w-4" />
      </Button>
    </Flex>
  )
}

/**
 * Display options for choice prompts (read-only fallback)
 */
const OptionsList: FC<{ options: string[] }> = ({ options }) => {
  return (
    <Flex direction="col" gap="1.5">
      {options.map((option, index) => (
        <Flex
          key={index}
          align="center"
          gap="2.5"
          className="agent-option-button rounded-[var(--radius-card)] border p-2.5"
        >
          <span className="agent-option-index">{index + 1}</span>
          <MarkdownRenderer
            content={option}
            compact
            className="text-primary min-w-0 flex-1 [&_p]:text-sm"
          />
        </Flex>
      ))}
    </Flex>
  )
}

/**
 * Display the user's response after submission: a quiet closure stamp.
 */
const ResponseDisplay: FC<{ response?: string }> = ({ response }) => {
  if (!response) return null

  return (
    <Flex align="center" gap="2.5" className="agent-response-receipt">
      <span className="agent-response-icon">
        <CheckCircle className="h-4 w-4" />
      </span>
      <Text kind="label/regular/sm" className="text-subtle shrink-0">
        You chose
      </Text>
      <MarkdownRenderer
        content={response}
        compact
        className="text-primary min-w-0 flex-1 [&_p]:text-sm"
      />
    </Flex>
  )
}

/**
 * Closure stamp for a plan approval prompt: confirms the decision.
 */
const ApprovalReceipt: FC<{ approved: boolean }> = ({ approved }) => (
  <Flex align="center" gap="2.5" className={cn('agent-response-receipt', !approved && 'is-reject')}>
    <span className="agent-response-icon">
      {approved ? <CheckCircle className="h-4 w-4" /> : <Close className="h-4 w-4" />}
    </span>
    <Text kind="label/semibold/sm" className="text-primary">
      {approved ? 'Plan approved' : 'Plan rejected'}
    </Text>
  </Flex>
)
