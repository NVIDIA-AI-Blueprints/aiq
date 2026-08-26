// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared agent-trace primitives consumed by both the inline chat trace
 * (ChatThinking) and the research panel.
 */

export { StatusDot, type NodeState } from './StatusDot'
export { ToolCallRow } from './ToolCallRow'
export {
  getAgentLabel,
  getToolLabel,
  isKnownTool,
  getToolArgSummary,
  formatModelName,
  statusToNodeState,
  todoStatusToNodeState,
} from './research-labels'
