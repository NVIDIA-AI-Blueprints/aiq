// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Chat Client Adapter
 *
 * Handles HTTP SSE streaming for OpenAI-compatible chat completions.
 * Uses the local /api/chat route to proxy requests to the backend,
 * avoiding CORS issues in the browser.
 */

import { apiConfig } from './config'
import {
  type Message,
  type ChatCompletionChunk,
  type ChatCompletionRequest,
  ChatCompletionChunkSchema,
} from './schemas'

export interface StreamChatOptions {
  messages: Message[]
  sessionId?: string
  model?: string
  temperature?: number
  maxTokens?: number
  signal?: AbortSignal
  /** Auth token (ID token or access token) for backend authentication */
  authToken?: string
}

export interface StreamCallbacks {
  onChunk: (content: string) => void
  onComplete?: () => void
  onError?: (error: Error) => void
}

/**
 * Stream chat completion from the backend
 *
 * @param options - Chat options including messages and configuration
 * @param callbacks - Callback functions for handling stream events
 */
export const streamChat = async (
  options: StreamChatOptions,
  callbacks: StreamCallbacks
): Promise<void> => {
  const { messages, sessionId, model, temperature, maxTokens, signal, authToken } =
    options
  const { onChunk, onComplete, onError } = callbacks

  const requestBody: ChatCompletionRequest = {
    messages,
    stream: true,
    session_id: sessionId,
    model,
    temperature,
    max_tokens: maxTokens,
  }

  // Build headers with optional auth token
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }

  try {
    // Use the local API route to avoid CORS issues
    // The API route proxies requests to the backend
    const response = await fetch(apiConfig.chatApiRoute, {
      method: 'POST',
      headers,
      body: JSON.stringify(requestBody),
      signal,
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(`Chat request failed: ${response.status} - ${errorText}`)
    }

    if (!response.body) {
      throw new Error('Response body is null')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()

      if (done) {
        onComplete?.()
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')

      // Keep the last incomplete line in the buffer
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmedLine = line.trim()

        if (!trimmedLine || !trimmedLine.startsWith('data: ')) {
          continue
        }

        const data = trimmedLine.slice(6) // Remove 'data: ' prefix

        if (data === '[DONE]') {
          onComplete?.()
          return
        }

        try {
          const parsed = JSON.parse(data)
          const validated = ChatCompletionChunkSchema.safeParse(parsed)

          if (validated.success) {
            const chunk: ChatCompletionChunk = validated.data
            const content = chunk.choices[0]?.delta?.content

            if (content) {
              onChunk(content)
            }

            // Check for completion
            if (chunk.choices[0]?.finish_reason === 'stop') {
              onComplete?.()
              return
            }
          }
        } catch {
          // Skip malformed JSON lines
          continue
        }
      }
    }
  } catch (error) {
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        // Request was cancelled, not an error
        return
      }
      onError?.(error)
    } else {
      onError?.(new Error('Unknown error occurred'))
    }
  }
}

/**
 * Non-streaming chat completion (for simple requests)
 */
export const sendChatMessage = async (
  options: Omit<StreamChatOptions, 'signal'>
): Promise<string> => {
  return new Promise((resolve, reject) => {
    let fullResponse = ''

    streamChat(
      { ...options },
      {
        onChunk: (content) => {
          fullResponse += content
        },
        onComplete: () => {
          resolve(fullResponse)
        },
        onError: (error) => {
          reject(error)
        },
      }
    )
  })
}

// ============================================================
// Generate Stream API - Routes content to appropriate panels
// ============================================================

/** Status types from the backend (subset of StatusType from features/chat/types) */
export type BackendStatusType =
  | 'thinking'
  | 'searching'
  | 'planning'
  | 'researching'
  | 'writing'
  | 'complete'
  | 'error'

/** Prompt types from the backend */
export type BackendPromptType = 'clarification' | 'approval' | 'choice' | 'text-input'

/** SSE message types from /generate/stream endpoint */
export type GenerateMessageType = 'status' | 'intermediate' | 'prompt' | 'report'

/** Parsed message from the generate stream */
export interface GenerateStreamMessage {
  type: GenerateMessageType
  // For status messages
  status?: BackendStatusType
  message?: string
  // For intermediate/thinking content
  content?: string
  // For prompt messages
  prompt_type?: BackendPromptType
  options?: string[]
  placeholder?: string
  // For report messages
  report?: string
}

export interface StreamGenerateOptions {
  /** User's input message */
  inputMessage: string
  /** Session ID for conversation tracking */
  sessionId?: string
  /** Abort signal */
  signal?: AbortSignal
  /** Auth token for backend authentication */
  authToken?: string
}

export interface GenerateStreamCallbacks {
  /** Called when intermediate/thinking content arrives - routes to Details Panel Thinking tab */
  onThinking: (content: string) => void
  /** Called when status update arrives - routes to Chat Area status card */
  onStatus: (statusType: BackendStatusType, message?: string) => void
  /** Called when agent needs user input - routes to Chat Area prompt */
  onPrompt: (
    promptType: BackendPromptType,
    content: string,
    options?: string[],
    placeholder?: string
  ) => void
  /** Called when final report arrives - routes to Details Panel Report tab */
  onReport: (content: string) => void
  /** Called when stream completes */
  onComplete?: () => void
  /** Called on error */
  onError?: (error: Error) => void
}

/**
 * OpenAI Chat Completion Response format (what backend actually returns)
 */
interface OpenAIChatCompletion {
  id: string
  object: 'chat.completion' | 'chat.completion.chunk'
  model: string
  created: number
  choices: Array<{
    index: number
    message?: { role: string; content: string }
    delta?: { role?: string; content?: string }
    finish_reason?: string | null
  }>
}

/**
 * Check if a parsed object is an OpenAI chat completion format
 */
const isOpenAIChatCompletion = (obj: unknown): obj is OpenAIChatCompletion => {
  return (
    typeof obj === 'object' &&
    obj !== null &&
    'object' in obj &&
    ((obj as OpenAIChatCompletion).object === 'chat.completion' ||
      (obj as OpenAIChatCompletion).object === 'chat.completion.chunk') &&
    'choices' in obj &&
    Array.isArray((obj as OpenAIChatCompletion).choices)
  )
}

/**
 * Stream generate from the backend's /generate/stream endpoint
 *
 * Routes different message types to appropriate UI panels:
 * - status -> Chat Area (status cards)
 * - intermediate -> Details Panel (Thinking tab)
 * - prompt -> Chat Area (agent prompts)
 * - report -> Details Panel (Report tab)
 * - OpenAI chat completion -> treated as final report
 *
 * @param options - Generate options including input message
 * @param callbacks - Callback functions for handling different message types
 */
export const streamGenerate = async (
  options: StreamGenerateOptions,
  callbacks: GenerateStreamCallbacks
): Promise<void> => {
  const { inputMessage, sessionId, signal, authToken } = options
  const { onThinking, onStatus, onPrompt, onReport, onComplete, onError } = callbacks

  const requestBody = {
    input_message: inputMessage,
    session_id: sessionId,
    stream: true,
  }

  // Build headers with optional auth token
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }

  try {
    // Use the local API route to avoid CORS issues
    const response = await fetch(apiConfig.generateApiRoute, {
      method: 'POST',
      headers,
      body: JSON.stringify(requestBody),
      signal,
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(`Generate request failed: ${response.status} - ${errorText}`)
    }

    if (!response.body) {
      throw new Error('Response body is null')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()

      if (done) {
        onComplete?.()
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')

      // Keep the last incomplete line in the buffer
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmedLine = line.trim()

        if (!trimmedLine || !trimmedLine.startsWith('data: ')) {
          continue
        }

        const data = trimmedLine.slice(6) // Remove 'data: ' prefix

        if (data === '[DONE]') {
          onComplete?.()
          return
        }

        try {
          const parsed = JSON.parse(data)

          // Check if this is OpenAI chat completion format (what the backend actually returns)
          if (isOpenAIChatCompletion(parsed)) {
            // Handle OpenAI format - extract content and treat as report
            const choice = parsed.choices[0]
            const content = choice?.message?.content || choice?.delta?.content || ''

            if (content) {
              // First, show a "complete" status
              onStatus('complete', 'Response received')
              // Then send the content to the report panel
              onReport(content)
            }

            // Check for completion
            if (choice?.finish_reason === 'stop') {
              onComplete?.()
              return
            }
            continue
          }

          // Handle our custom message format (for future compatibility)
          const customMessage = parsed as GenerateStreamMessage

          // Route message to appropriate callback based on type
          switch (customMessage.type) {
            case 'status':
              if (customMessage.status) {
                onStatus(customMessage.status, customMessage.message)
              }
              break

            case 'intermediate':
              if (customMessage.content) {
                onThinking(customMessage.content)
              }
              break

            case 'prompt':
              if (customMessage.prompt_type && customMessage.content) {
                onPrompt(
                  customMessage.prompt_type,
                  customMessage.content,
                  customMessage.options,
                  customMessage.placeholder
                )
              }
              break

            case 'report':
              if (customMessage.content || customMessage.report) {
                onReport(customMessage.content || customMessage.report || '')
              }
              break

            default:
              // Unknown message type - try to extract content anyway
              if ('content' in parsed && typeof parsed.content === 'string') {
                onReport(parsed.content)
              } else {
                console.warn('Unknown generate stream message format:', parsed)
              }
          }
        } catch {
          // Skip malformed JSON lines
          continue
        }
      }
    }
  } catch (error) {
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        // Request was cancelled, not an error
        return
      }
      onError?.(error)
    } else {
      onError?.(new Error('Unknown error occurred'))
    }
  }
}

/**
 * Send a prompt response to the backend
 * This is called when the user responds to an agent prompt
 */
export const sendPromptResponse = async (
  sessionId: string,
  promptId: string,
  response: string,
  authToken?: string
): Promise<void> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }

  const apiResponse = await fetch(`${apiConfig.generateApiRoute}/respond`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      session_id: sessionId,
      prompt_id: promptId,
      response,
    }),
  })

  if (!apiResponse.ok) {
    const errorText = await apiResponse.text()
    throw new Error(`Prompt response failed: ${apiResponse.status} - ${errorText}`)
  }
}
