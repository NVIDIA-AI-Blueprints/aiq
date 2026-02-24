// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Chat Components
 *
 * Reusable components for the chat feature.
 */

// Message components
export { UserMessage } from './UserMessage'
export type { UserMessageProps } from './UserMessage'

export { AgentPrompt } from './AgentPrompt'
export type { AgentPromptProps, PromptType } from './AgentPrompt'

export { AgentResponse } from './AgentResponse'
export type { AgentResponseProps } from './AgentResponse'

// Banner components
export { FileUploadBanner } from './FileUploadBanner'
export type { FileUploadBannerProps } from './FileUploadBanner'

export { ErrorBanner } from './ErrorBanner'
export type { ErrorBannerProps, ErrorCode } from './ErrorBanner'

export { DeepResearchBanner } from './DeepResearchBanner'
export type { DeepResearchBannerProps } from './DeepResearchBanner'

export { NoSourcesBanner } from './NoSourcesBanner'

// Thinking/status components
export { ChatThinking } from './ChatThinking'
export type { ChatThinkingProps } from './ChatThinking'
