// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * API Schemas and Types
 *
 * Zod schemas for runtime validation of API responses.
 * All external data passes through these schemas at the adapter boundary.
 */

import { z } from 'zod'

// ============================================================================
// Chat Completion API (OpenAI-Compatible)
// ============================================================================

export const MessageSchema = z.object({
  role: z.enum(['system', 'user', 'assistant']),
  content: z.string(),
  name: z.string().optional(),
})

export const ChatCompletionRequestSchema = z.object({
  messages: z.array(MessageSchema),
  model: z.string().optional(),
  temperature: z.number().optional(),
  max_tokens: z.number().optional(),
  stream: z.boolean().optional(),
  session_id: z.string().optional(),
})

export const ChatCompletionChoiceSchema = z.object({
  index: z.number(),
  delta: z.object({
    role: z.enum(['assistant']).optional(),
    content: z.string().optional(),
  }),
  finish_reason: z.enum(['stop', 'length', 'tool_calls']).nullable(),
})

export const ChatCompletionChunkSchema = z.object({
  id: z.string(),
  object: z.literal('chat.completion.chunk'),
  created: z.number(),
  model: z.string(),
  choices: z.array(ChatCompletionChoiceSchema),
})

// ============================================================================
// WebSocket Protocol (NAT Compatible)
// ============================================================================

/** NAT WebSocket message types */
export const NATMessageType = {
  USER_MESSAGE: 'user_message',
  SYSTEM_RESPONSE: 'system_response_message',
  SYSTEM_INTERMEDIATE: 'system_intermediate_message',
  SYSTEM_INTERACTION: 'system_interaction_message',
  USER_INTERACTION: 'user_interaction_message',
  OBSERVABILITY_TRACE: 'observability_trace_message',
  ERROR: 'error_message',
} as const

/** NAT workflow schema types */
export const NATSchemaType = {
  GENERATE: 'generate',
  GENERATE_STREAM: 'generate_stream',
  CHAT: 'chat',
  CHAT_STREAM: 'chat_stream',
} as const

/** Human prompt input types from NAT */
export const HumanPromptType = {
  TEXT: 'text',
  MULTIPLE_CHOICE: 'multiple_choice',
  BINARY_CHOICE: 'binary_choice',
  APPROVAL: 'approval',
  NOTIFICATION: 'notification',
  OAUTH_CONSENT: 'oauth_consent',
} as const

/** Message status for WebSocket messages */
export const WebSocketMessageStatus = {
  IN_PROGRESS: 'in_progress',
  COMPLETE: 'complete',
  ERROR: 'error',
} as const

// ----------------------------------------------------------------------------
// Outgoing Messages (Client -> Server)
// ----------------------------------------------------------------------------

/** Text content item for user messages (matches backend UserContent) */
export const NATUserContentTextSchema = z.object({
  type: z.literal('text'),
  text: z.string(),
})

/** User message item (matches backend UserMessages) */
export const NATUserMessageItemSchema = z.object({
  role: z.enum(['user', 'assistant', 'system']),
  content: z.array(NATUserContentTextSchema),
})

/** User message content schema (matches backend UserMessageContent) */
export const NATUserMessageContentSchema = z.object({
  messages: z.array(NATUserMessageItemSchema),
})

/** NAT User Message - sent when user submits a chat message */
export const NATUserMessageSchema = z.object({
  type: z.literal(NATMessageType.USER_MESSAGE),
  schema_type: z.enum([
    NATSchemaType.GENERATE,
    NATSchemaType.GENERATE_STREAM,
    NATSchemaType.CHAT,
    NATSchemaType.CHAT_STREAM,
  ]),
  id: z.string().optional(),
  conversation_id: z.string().optional(),
  content: NATUserMessageContentSchema,
  timestamp: z.string().optional(),
  /** Optional list of enabled data source IDs to include in the query */
  enabled_data_sources: z.array(z.string()).optional(),
})

/** NAT User Interaction Response - sent when user responds to a prompt */
export const NATUserInteractionResponseSchema = z.object({
  type: z.literal(NATMessageType.USER_INTERACTION),
  id: z.string(),
  parent_id: z.string(),
  conversation_id: z.string().optional(),
  content: NATUserMessageContentSchema, // Same structure as user messages
  timestamp: z.string().optional(),
})

// ----------------------------------------------------------------------------
// Incoming Messages (Server -> Client)
// ----------------------------------------------------------------------------

/** Human prompt content - for clarification, approval, choices */
export const NATHumanPromptSchema = z.object({
  input_type: z.enum([
    HumanPromptType.TEXT,
    HumanPromptType.MULTIPLE_CHOICE,
    HumanPromptType.BINARY_CHOICE,
    HumanPromptType.APPROVAL,
    HumanPromptType.NOTIFICATION,
    HumanPromptType.OAUTH_CONSENT,
  ]),
  text: z.string(),
  /** Options for multiple choice prompts */
  options: z.array(z.string()).optional(),
  /** Default value for text input */
  default_value: z.string().optional(),
})

/** System Interaction Message - human prompt from agent */
export const NATSystemInteractionMessageSchema = z.object({
  type: z.literal(NATMessageType.SYSTEM_INTERACTION),
  id: z.string(),
  thread_id: z.string().optional(),
  parent_id: z.string(),
  conversation_id: z.string().optional(),
  content: NATHumanPromptSchema,
  status: z.enum([
    WebSocketMessageStatus.IN_PROGRESS,
    WebSocketMessageStatus.COMPLETE,
    WebSocketMessageStatus.ERROR,
  ]),
  timestamp: z.string().optional(),
})

/** System response content (SystemResponseContent format) */
export const NATSystemResponseContentSchema = z.object({
  role: z.literal('assistant').optional(),
  text: z.string().nullable().optional(),
})

/** Generate response content (GenerateResponse format - used by shallow/meta responses) */
export const NATGenerateResponseContentSchema = z.object({
  output: z.string(),
  value: z.string().optional(),
  intermediate_steps: z.array(z.unknown()).nullable().optional(),
})

/** System Response Message - final or streaming response */
export const NATSystemResponseMessageSchema = z.object({
  type: z.literal(NATMessageType.SYSTEM_RESPONSE),
  id: z.string().optional(),
  thread_id: z.string().optional(),
  parent_id: z.string().optional(),
  conversation_id: z.string().optional(),
  // Content can be: string, SystemResponseContent (with text), or GenerateResponse (with output)
  content: NATSystemResponseContentSchema.or(NATGenerateResponseContentSchema).or(z.string()),
  status: z.enum([
    WebSocketMessageStatus.IN_PROGRESS,
    WebSocketMessageStatus.COMPLETE,
    WebSocketMessageStatus.ERROR,
  ]),
  timestamp: z.string().optional(),
})

/** Intermediate step content */
export const NATIntermediateStepContentSchema = z.object({
  name: z.string(),
  payload: z.string(),
})

/** System Intermediate Message - thinking steps, tool calls */
export const NATSystemIntermediateMessageSchema = z.object({
  type: z.literal(NATMessageType.SYSTEM_INTERMEDIATE),
  id: z.string().optional(),
  thread_id: z.string().optional(),
  parent_id: z.string().optional(),
  conversation_id: z.string().optional(),
  content: NATIntermediateStepContentSchema.or(z.string()),
  status: z.enum([
    WebSocketMessageStatus.IN_PROGRESS,
    WebSocketMessageStatus.COMPLETE,
    WebSocketMessageStatus.ERROR,
  ]),
  timestamp: z.string().optional(),
})

/** Error content */
export const NATErrorContentSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.string().optional(),
})

/** Error Message */
export const NATErrorMessageSchema = z.object({
  type: z.literal(NATMessageType.ERROR),
  id: z.string().optional(),
  conversation_id: z.string().optional(),
  content: NATErrorContentSchema,
  status: z.literal(WebSocketMessageStatus.ERROR).optional(),
  timestamp: z.string().optional(),
})

/** Union of all incoming NAT WebSocket messages */
export const NATIncomingMessageSchema = z.discriminatedUnion('type', [
  NATSystemResponseMessageSchema,
  NATSystemIntermediateMessageSchema,
  NATSystemInteractionMessageSchema,
  NATErrorMessageSchema,
])

// ----------------------------------------------------------------------------
// Legacy WebSocket Protocol (kept for backwards compatibility)
// ----------------------------------------------------------------------------

export const WebSocketConnectMessageSchema = z.object({
  type: z.literal('connect'),
  session_id: z.string(),
  /** Auth token for backend authentication */
  auth_token: z.string().optional(),
})

export const WebSocketUserMessageSchema = z.object({
  type: z.literal('message'),
  content: z.string(),
  session_id: z.string(),
})

export const WebSocketAgentTextMessageSchema = z.object({
  type: z.literal('agent_text'),
  content: z.string(),
  is_final: z.boolean(),
})

export const WebSocketStatusMessageSchema = z.object({
  type: z.literal('status'),
  status: z.enum(['thinking', 'processing', 'complete', 'error']),
  message: z.string().optional(),
})

export const WebSocketToolCallMessageSchema = z.object({
  type: z.literal('tool_call'),
  tool_name: z.string(),
  tool_input: z.record(z.unknown()),
  tool_output: z.string().optional(),
})

export const WebSocketErrorMessageSchema = z.object({
  type: z.literal('error'),
  code: z.string(),
  message: z.string(),
})

export const WebSocketIncomingMessageSchema = z.discriminatedUnion('type', [
  WebSocketAgentTextMessageSchema,
  WebSocketStatusMessageSchema,
  WebSocketToolCallMessageSchema,
  WebSocketErrorMessageSchema,
])

// ============================================================================
// Workflow Configuration
// ============================================================================

export const WorkflowConfigSchema = z.object({
  Workflow: z.object({
    DisplayName: z.string(),
    Description: z.string(),
    Version: z.string(),
  }),
  Application: z.object({
    EnableConversationSideBar: z.boolean(),
    EnableFeedback: z.boolean(),
    EnableFileUpload: z.boolean(),
    MaxFileSize: z.number(),
    AllowedFileTypes: z.array(z.string()),
  }),
  Chat: z.object({
    SystemPrompt: z.string(),
    WelcomeMessage: z.string(),
    SuggestedQuestions: z.array(z.string()),
    MaxTokens: z.number(),
    Temperature: z.number(),
  }),
  Theme: z.object({
    PrimaryColor: z.string(),
    LogoUrl: z.string(),
    FaviconUrl: z.string(),
  }),
})

// ============================================================================
// Error Response
// ============================================================================

export const ApiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.unknown()).optional(),
  }),
})

// ============================================================================
// Type Exports
// ============================================================================

export type Message = z.infer<typeof MessageSchema>
export type ChatCompletionRequest = z.infer<typeof ChatCompletionRequestSchema>
export type ChatCompletionChunk = z.infer<typeof ChatCompletionChunkSchema>
export type ChatCompletionChoice = z.infer<typeof ChatCompletionChoiceSchema>

// NAT WebSocket Types
export type NATUserMessage = z.infer<typeof NATUserMessageSchema>
export type NATUserMessageContent = z.infer<typeof NATUserMessageContentSchema>
export type NATUserMessageItem = z.infer<typeof NATUserMessageItemSchema>
export type NATUserContentText = z.infer<typeof NATUserContentTextSchema>
export type NATUserInteractionResponse = z.infer<typeof NATUserInteractionResponseSchema>
export type NATHumanPrompt = z.infer<typeof NATHumanPromptSchema>
export type NATSystemInteractionMessage = z.infer<typeof NATSystemInteractionMessageSchema>
export type NATSystemResponseMessage = z.infer<typeof NATSystemResponseMessageSchema>
export type NATSystemResponseContent = z.infer<typeof NATSystemResponseContentSchema>
export type NATSystemIntermediateMessage = z.infer<typeof NATSystemIntermediateMessageSchema>
export type NATIntermediateStepContent = z.infer<typeof NATIntermediateStepContentSchema>
export type NATErrorMessage = z.infer<typeof NATErrorMessageSchema>
export type NATErrorContent = z.infer<typeof NATErrorContentSchema>
export type NATIncomingMessage = z.infer<typeof NATIncomingMessageSchema>

// Legacy WebSocket Types (kept for backwards compatibility)
export type WebSocketConnectMessage = z.infer<typeof WebSocketConnectMessageSchema>
export type WebSocketUserMessage = z.infer<typeof WebSocketUserMessageSchema>
export type WebSocketAgentTextMessage = z.infer<typeof WebSocketAgentTextMessageSchema>
export type WebSocketStatusMessage = z.infer<typeof WebSocketStatusMessageSchema>
export type WebSocketToolCallMessage = z.infer<typeof WebSocketToolCallMessageSchema>
export type WebSocketErrorMessage = z.infer<typeof WebSocketErrorMessageSchema>
export type WebSocketIncomingMessage = z.infer<typeof WebSocketIncomingMessageSchema>

export type WorkflowConfig = z.infer<typeof WorkflowConfigSchema>
export type ApiError = z.infer<typeof ApiErrorSchema>
