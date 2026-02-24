// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * WebSocket Client Adapter
 *
 * Handles WebSocket connections for the NAT protocol.
 * Supports system_response, system_intermediate, system_interaction,
 * and error message types for full HITL (human-in-the-loop) support.
 */

import { getWebSocketUrl } from './config'
import {
  // NAT protocol types
  type NATIncomingMessage,
  type NATUserMessage,
  type NATUserInteractionResponse,
  type NATHumanPrompt,
  type NATIntermediateStepContent,
  type NATErrorContent,
  NATIncomingMessageSchema,
  NATMessageType,
  NATSchemaType,
  HumanPromptType,
} from './schemas'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

/** Context passed with connection status changes */
export interface ConnectionChangeContext {
  /** Whether the disconnect was intentional (e.g. session switch, cleanup) */
  intentional?: boolean
}

/** Callbacks for NAT WebSocket client */
export interface NATWebSocketClientCallbacks {
  /** Called when a system response message arrives (final or streaming content) */
  onResponse?: (content: string, status: string, isFinal: boolean) => void
  /** Called when intermediate steps arrive (thinking, tool calls) */
  onIntermediateStep?: (content: NATIntermediateStepContent | string, status: string) => void
  /** Called when a human prompt arrives (clarification, approval, etc.) */
  onHumanPrompt?: (promptId: string, parentId: string, prompt: NATHumanPrompt) => void
  /** Called when an error occurs */
  onError?: (error: NATErrorContent) => void
  /** Called when connection status changes */
  onConnectionChange?: (status: ConnectionStatus, context?: ConnectionChangeContext) => void
}

/** Options for NAT WebSocket client */
export interface NATWebSocketClientOptions {
  /** Conversation/session ID */
  conversationId: string
  /** Callback functions */
  callbacks: NATWebSocketClientCallbacks
  /** Number of reconnection attempts (default: 3) */
  reconnectAttempts?: number
  /** Delay between reconnection attempts in ms (default: 1000) */
  reconnectDelay?: number
  /** Auth token for backend authentication */
  authToken?: string
  /** Override WebSocket URL (uses same-origin by default, proxied through UI server) */
  websocketUrl?: string
}

/**
 * NAT WebSocket client for AI-Q backend communication.
 * Supports full human-in-the-loop (HITL) features including
 * clarification prompts and approval flows.
 */
export class NATWebSocketClient {
  private ws: WebSocket | null = null
  private options: NATWebSocketClientOptions
  private reconnectCount = 0
  private isIntentionallyClosed = false
  private errorBeforeClose = false
  private messageIdCounter = 0

  constructor(options: NATWebSocketClientOptions) {
    this.options = {
      reconnectAttempts: 3,
      reconnectDelay: 1000,
      ...options,
    }
  }

  /**
   * Generate a unique message ID
   */
  private generateMessageId = (): string => {
    this.messageIdCounter++
    return `msg_${Date.now()}_${this.messageIdCounter}`
  }

  /**
   * Connect to the WebSocket server
   */
  connect = async (): Promise<void> => {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    this.isIntentionallyClosed = false
    this.options.callbacks.onConnectionChange?.('connecting')

    try {
      const baseWsUrl = this.options.websocketUrl || (await getWebSocketUrl())
      let wsUrl = baseWsUrl
      if (this.options.authToken) {
        const separator = wsUrl.includes('?') ? '&' : '?'
        wsUrl = `${wsUrl}${separator}token=${encodeURIComponent(this.options.authToken)}`
      }

      this.ws = new WebSocket(wsUrl)
      this.setupEventHandlers()
    } catch {
      this.options.callbacks.onConnectionChange?.('error', { intentional: false })
      this.handleReconnect()
    }
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect = (): void => {
    this.isIntentionallyClosed = true
    this.reconnectCount = 0

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.options.callbacks.onConnectionChange?.('disconnected', { intentional: true })
  }

  /**
   * Send a user chat message
   * @param content - The message text content (query)
   * @param enabledDataSources - Optional array of enabled data source IDs to include in the query
   */
  sendMessage = (content: string, enabledDataSources?: string[]): void => {
    // Format the text content as JSON with query and data_sources
    const textContent = JSON.stringify({
      query: content,
      data_sources: enabledDataSources ?? [],
    })

    const message: NATUserMessage = {
      type: NATMessageType.USER_MESSAGE,
      schema_type: NATSchemaType.CHAT_STREAM,
      id: this.generateMessageId(),
      conversation_id: this.options.conversationId,
      content: {
        messages: [
          {
            role: 'user',
            content: [{ type: 'text', text: textContent }],
          },
        ],
      },
      timestamp: new Date().toISOString(),
    }

    this.send(message)
  }

  /**
   * Send a response to a human prompt (clarification, approval, etc.)
   */
  sendInteractionResponse = (promptId: string, parentId: string, responseText: string): void => {
    const message: NATUserInteractionResponse = {
      type: NATMessageType.USER_INTERACTION,
      id: this.generateMessageId(),
      parent_id: parentId,
      conversation_id: this.options.conversationId,
      content: {
        messages: [
          {
            role: 'user',
            content: [{ type: 'text', text: responseText }],
          },
        ],
      },
      timestamp: new Date().toISOString(),
    }

    this.send(message)
  }

  /**
   * Check if connected
   */
  isConnected = (): boolean => {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /**
   * Update the auth token (e.g., after refresh)
   */
  updateAuthToken = (authToken: string): void => {
    this.options.authToken = authToken
  }

  /**
   * Update conversation ID (e.g., when switching conversations)
   */
  updateConversationId = (conversationId: string): void => {
    this.options.conversationId = conversationId
  }

  private setupEventHandlers = (): void => {
    if (!this.ws) return

    this.ws.onopen = () => {
      this.reconnectCount = 0
      this.errorBeforeClose = false
      this.options.callbacks.onConnectionChange?.('connected')
    }

    this.ws.onerror = () => {
      // Flag that an error preceded the close event.
      // Don't fire onConnectionChange here -- onclose always follows onerror
      // in the browser WebSocket API. This prevents double-firing.
      this.errorBeforeClose = true
    }

    this.ws.onclose = () => {
      const hadError = this.errorBeforeClose
      this.errorBeforeClose = false

      if (this.isIntentionallyClosed) {
        // Intentional close (session switch, cleanup) -- already handled by disconnect()
        return
      }

      // During active reconnection, suppress status callbacks to avoid
      // intermediate error/disconnected flickers. Only fire on:
      // - Successful reconnection (handled by onopen above)
      // - Final failure after all retries (handled by handleReconnect)
      if (this.reconnectCount > 0) {
        this.handleReconnect()
        return
      }

      // First disconnect -- notify with appropriate status
      const status: ConnectionStatus = hadError ? 'error' : 'disconnected'
      this.options.callbacks.onConnectionChange?.(status, { intentional: false })
      this.handleReconnect()
    }

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data)
    }
  }

  private handleMessage = (data: string): void => {
    try {
      const parsed = JSON.parse(data)
      const validated = NATIncomingMessageSchema.safeParse(parsed)

      if (!validated.success) {
        console.warn('Invalid NAT WebSocket message:', validated.error, parsed)
        return
      }

      const message: NATIncomingMessage = validated.data

      switch (message.type) {
        case NATMessageType.SYSTEM_RESPONSE: {
          // Extract content - can be:
          // - string (direct content)
          // - SystemResponseContent with .text field
          // - GenerateResponse with .output field (shallow/meta responses)
          let content = ''
          if (typeof message.content === 'string') {
            content = message.content
          } else if ('output' in message.content && message.content.output != null) {
            // GenerateResponse format (shallow/meta responses)
            content = message.content.output
          } else if ('text' in message.content && message.content.text != null) {
            // SystemResponseContent format
            content = message.content.text
          }


          const isFinal = message.status === 'complete'
          this.options.callbacks.onResponse?.(content, message.status, isFinal)
          break
        }

        case NATMessageType.SYSTEM_INTERMEDIATE: {
          this.options.callbacks.onIntermediateStep?.(message.content, message.status)
          break
        }

        case NATMessageType.SYSTEM_INTERACTION: {
          // Human prompt - needs user response
          this.options.callbacks.onHumanPrompt?.(message.id, message.parent_id, message.content)
          break
        }

        case NATMessageType.ERROR: {
          this.options.callbacks.onError?.(message.content)
          break
        }
      }
    } catch {
      console.warn('Failed to parse NAT WebSocket message:', data)
    }
  }

  private send = (message: object): void => {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    } else {
      console.warn('NAT WebSocket not connected, message not sent')
    }
  }

  private handleReconnect = (): void => {
    const { reconnectAttempts, reconnectDelay } = this.options

    if (this.reconnectCount >= (reconnectAttempts || 3)) {
      // All retries exhausted -- notify with final disconnected status
      this.options.callbacks.onConnectionChange?.('disconnected', { intentional: false })
      this.options.callbacks.onError?.({
        code: 'CONNECTION_FAILED',
        message: 'Unable to connect to the server. Please check your network connection.',
      })
      return
    }

    this.reconnectCount++

    setTimeout(() => {
      if (!this.isIntentionallyClosed) {
        this.connect()
      }
    }, reconnectDelay || 1000)
  }
}

/**
 * Create a new NAT WebSocket client instance
 */
export const createNATWebSocketClient = (
  options: NATWebSocketClientOptions
): NATWebSocketClient => {
  return new NATWebSocketClient(options)
}

// Re-export NAT types for convenience
export { NATMessageType, NATSchemaType, HumanPromptType }
export type { NATHumanPrompt, NATIntermediateStepContent, NATErrorContent }
