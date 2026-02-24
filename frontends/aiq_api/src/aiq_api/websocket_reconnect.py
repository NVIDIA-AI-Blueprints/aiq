# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reconnectable WebSocket handler for HITL interactions."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import WebSocket
from pydantic import BaseModel
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from nat.data_models.api_server import Error
from nat.data_models.api_server import ErrorTypes
from nat.data_models.api_server import ResponseObservabilityTrace
from nat.data_models.api_server import SystemResponseContent
from nat.data_models.api_server import TextContent
from nat.data_models.api_server import WebSocketMessageStatus
from nat.data_models.api_server import WebSocketMessageType
from nat.data_models.api_server import WebSocketObservabilityTraceMessage
from nat.data_models.api_server import WebSocketSystemInteractionMessage
from nat.data_models.api_server import WebSocketSystemIntermediateStepMessage
from nat.data_models.api_server import WebSocketSystemResponseTokenMessage
from nat.data_models.api_server import WebSocketUserInteractionResponseMessage
from nat.data_models.api_server import WebSocketUserMessage
from nat.data_models.interactive import HumanPromptNotification
from nat.data_models.interactive import HumanResponse
from nat.data_models.interactive import HumanResponseNotification
from nat.data_models.interactive import InteractionPrompt
from nat.front_ends.fastapi.message_handler import WebSocketMessageHandler
from nat.front_ends.fastapi.response_helpers import generate_streaming_response

logger = logging.getLogger(__name__)


class WebSocketSessionRegistry:
    """Keep track of active sockets and pending HITL responses."""

    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}
        self._pending_interactions: dict[str, asyncio.Future[TextContent]] = {}
        self._lock = asyncio.Lock()

    async def set_socket(self, conversation_id: str | None, socket: WebSocket) -> None:
        """Register the latest socket for a conversation."""
        if not conversation_id:
            return
        async with self._lock:
            self._sockets[conversation_id] = socket

    async def clear_socket(self, conversation_id: str | None, socket: WebSocket) -> None:
        """Clear the socket only if it matches the current one."""
        if not conversation_id:
            return
        async with self._lock:
            current = self._sockets.get(conversation_id)
            if current is socket:
                self._sockets.pop(conversation_id, None)

    async def send(self, conversation_id: str | None, message: BaseModel) -> bool:
        """Send a message to the current socket for a conversation."""
        if not conversation_id:
            return False
        async with self._lock:
            socket = self._sockets.get(conversation_id)
        if not socket:
            return False
        try:
            await socket.send_json(message.model_dump())
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to send websocket message after reconnect: %s", exc)
            return False

    async def register_pending_interaction(
        self,
        conversation_id: str | None,
        future: asyncio.Future[TextContent],
    ) -> None:
        """Store the pending HITL future for a conversation."""
        if not conversation_id:
            return
        async with self._lock:
            self._pending_interactions[conversation_id] = future

    async def resolve_pending_interaction(
        self,
        conversation_id: str | None,
        user_content: TextContent,
    ) -> bool:
        """Resolve a pending HITL future if it exists."""
        if not conversation_id:
            return False
        async with self._lock:
            future = self._pending_interactions.get(conversation_id)
            if future is None or future.done():
                return False
            future.set_result(user_content)
            self._pending_interactions.pop(conversation_id, None)
            return True

    async def clear_pending_interaction(self, conversation_id: str | None) -> None:
        """Clear pending interaction state once resolved."""
        if not conversation_id:
            return
        async with self._lock:
            self._pending_interactions.pop(conversation_id, None)


_registry = WebSocketSessionRegistry()
_installed = False


class ReconnectableWebSocketMessageHandler(WebSocketMessageHandler):
    """WebSocket handler that supports HITL reconnects per conversation."""

    async def run(self) -> None:
        """Process websocket messages and allow reconnect HITL responses."""
        while True:
            try:
                message: dict[str, Any] = await self._socket.receive_json()
                validated_message: BaseModel = await self._message_validator.validate_message(message)

                if isinstance(validated_message, WebSocketUserMessage):
                    await self.process_workflow_request(validated_message)
                    await _registry.set_socket(validated_message.conversation_id, self._socket)

                elif isinstance(
                    validated_message,
                    WebSocketSystemResponseTokenMessage
                    | WebSocketSystemIntermediateStepMessage
                    | WebSocketSystemInteractionMessage,
                ):
                    pass

                elif isinstance(validated_message, WebSocketUserInteractionResponseMessage):
                    user_content = await self._process_websocket_user_interaction_response_message(validated_message)
                    await _registry.set_socket(validated_message.conversation_id, self._socket)
                    if self._user_interaction_response is not None:
                        self._user_interaction_response.set_result(user_content)
                    else:
                        resolved = await _registry.resolve_pending_interaction(
                            validated_message.conversation_id, user_content
                        )
                        if not resolved:
                            logger.warning(
                                "No pending HITL interaction to resume for conversation %s",
                                validated_message.conversation_id,
                            )
            except (asyncio.CancelledError, WebSocketDisconnect):
                await _registry.clear_socket(self._conversation_id, self._socket)
                break
            except ValidationError as exc:
                logger.warning("Invalid websocket message payload: %s", str(exc))

    async def process_workflow_request(self, user_message_as_validated_type: WebSocketUserMessage) -> None:
        """Process user messages and register sockets for reconnect."""
        await _registry.set_socket(user_message_as_validated_type.conversation_id, self._socket)
        await super().process_workflow_request(user_message_as_validated_type)

    async def create_websocket_message(
        self,
        data_model: BaseModel,
        message_type: str | None = None,
        status: WebSocketMessageStatus = WebSocketMessageStatus.IN_PROGRESS,
    ) -> None:
        """Create a websocket message and send via the registry."""
        message: BaseModel | None = None
        try:
            if message_type is None:
                message_type = await self._message_validator.resolve_message_type_by_data(data_model)

            message_schema: type[BaseModel] = await self._message_validator.get_message_schema_by_type(message_type)

            if hasattr(data_model, "id"):
                message_id: str = str(getattr(data_model, "id"))
            else:
                message_id = str(uuid.uuid4())

            content: BaseModel = await self._message_validator.convert_data_to_message_content(data_model)

            if issubclass(message_schema, WebSocketSystemResponseTokenMessage):
                message = await self._message_validator.create_system_response_token_message(
                    message_id=message_id,
                    parent_id=self._message_parent_id,
                    conversation_id=self._conversation_id,
                    content=content,
                    status=status,
                )

            elif issubclass(message_schema, WebSocketSystemIntermediateStepMessage):
                message = await self._message_validator.create_system_intermediate_step_message(
                    message_id=message_id,
                    parent_id=await self._message_validator.get_intermediate_step_parent_id(data_model),
                    conversation_id=self._conversation_id,
                    content=content,
                    status=status,
                )

            elif issubclass(message_schema, WebSocketSystemInteractionMessage):
                message = await self._message_validator.create_system_interaction_message(
                    message_id=message_id,
                    parent_id=self._message_parent_id,
                    conversation_id=self._conversation_id,
                    content=content,
                    status=status,
                )

            elif issubclass(message_schema, WebSocketObservabilityTraceMessage):
                message = await self._message_validator.create_observability_trace_message(
                    message_id=message_id,
                    parent_id=self._message_parent_id,
                    conversation_id=self._conversation_id,
                    content=content,
                )

            elif isinstance(content, Error):
                raise ValueError(f"Invalid input data creating websocket message. {data_model.model_dump_json()}")

            elif issubclass(message_schema, Error):
                raise TypeError(f"Invalid message type: {message_type}")

            elif message is None:
                raise ValueError(
                    f"Message type could not be resolved by input data model: {data_model.model_dump_json()}"
                )

        except (ValidationError, ValueError, TypeError) as exc:
            logger.exception("A data validation error occurred creating websocket message: %s", str(exc))
            message = await self._message_validator.create_system_response_token_message(
                message_type=WebSocketMessageType.ERROR_MESSAGE,
                conversation_id=self._conversation_id,
                content=Error(code=ErrorTypes.UNKNOWN_ERROR, message="default", details=str(exc)),
            )

        finally:
            if message is not None:
                sent = await _registry.send(self._conversation_id, message)
                if not sent:
                    try:
                        await self._socket.send_json(message.model_dump())
                    except Exception as exc:  # pragma: no cover - socket may be closed
                        logger.warning("Failed to send websocket message: %s", exc)

    async def human_interaction_callback(self, prompt: InteractionPrompt) -> HumanResponse:
        """
        Handle HITL prompts and register response futures for reconnect.
        """
        human_response_future: asyncio.Future[TextContent] = asyncio.get_running_loop().create_future()
        self._user_interaction_response = human_response_future
        await _registry.register_pending_interaction(self._conversation_id, human_response_future)

        try:
            await self.create_websocket_message(
                data_model=prompt.content,
                message_type=WebSocketMessageType.SYSTEM_INTERACTION_MESSAGE,
                status=WebSocketMessageStatus.IN_PROGRESS,
            )

            if isinstance(prompt.content, HumanPromptNotification):
                return HumanResponseNotification()

            text_content: TextContent = await human_response_future
            interaction_response: HumanResponse = await self._message_validator.convert_text_content_to_human_response(
                text_content, prompt.content
            )
            return interaction_response
        finally:
            await _registry.clear_pending_interaction(self._conversation_id)
            self._user_interaction_response = None

    async def _run_workflow(
        self,
        payload: Any,
        user_message_id: str | None = None,
        conversation_id: str | None = None,
        result_type: type | None = None,
        output_type: type | None = None,
    ) -> None:
        """Run the workflow without breaking reconnect message delivery."""
        try:
            auth_callback = self._flow_handler.authenticate if self._flow_handler else None
            async with self._session_manager.session(
                user_message_id=user_message_id,
                conversation_id=conversation_id,
                http_connection=self._socket,
                user_input_callback=self.human_interaction_callback,
                user_authentication_callback=auth_callback,
            ) as session:
                async for value in generate_streaming_response(
                    payload,
                    session=session,
                    streaming=True,
                    step_adaptor=self._step_adaptor,
                    result_type=result_type,
                    output_type=output_type,
                ):
                    if isinstance(value, ResponseObservabilityTrace):
                        if self._pending_observability_trace is None:
                            self._pending_observability_trace = value
                    else:
                        await self.create_websocket_message(
                            data_model=value,
                            status=WebSocketMessageStatus.IN_PROGRESS,
                        )

            await self.create_websocket_message(
                data_model=SystemResponseContent(),
                message_type=WebSocketMessageType.RESPONSE_MESSAGE,
                status=WebSocketMessageStatus.COMPLETE,
            )

            if self._pending_observability_trace:
                await self.create_websocket_message(
                    data_model=self._pending_observability_trace,
                    message_type=WebSocketMessageType.OBSERVABILITY_TRACE_MESSAGE,
                )
                self._pending_observability_trace = None
        except Exception:
            logger.exception("Error running workflow")


def install_reconnectable_handler() -> None:  # TODO: upstream to NAT
    """Monkeypatch NAT to use reconnectable websocket handler."""
    global _installed
    if _installed:
        return
    from nat.front_ends.fastapi import fastapi_front_end_plugin_worker as worker_module

    worker_module.WebSocketMessageHandler = ReconnectableWebSocketMessageHandler
    _installed = True
