# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiq_api.auth.errors import AuthError
from aiq_api.websocket_reconnect import ReconnectableWebSocketMessageHandler
from nat.data_models.api_server import ErrorTypes
from nat.data_models.api_server import WebSocketMessageStatus
from nat.data_models.api_server import WebSocketMessageType


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SessionManager:
    def session(self, **kwargs):
        return _SessionContext()


async def _raise_auth_error(*args, **kwargs):
    if False:  # pragma: no cover - keeps this as an async generator
        yield None
    raise AuthError("token expired")


class TestWebSocketAuthErrors:
    @pytest.mark.asyncio
    async def test_run_workflow_emits_auth_error_message(self, monkeypatch):
        monkeypatch.setattr("aiq_api.websocket_reconnect.generate_streaming_response", _raise_auth_error)

        handler = SimpleNamespace(
            _flow_handler=None,
            _session_manager=_SessionManager(),
            _socket=object(),
            _authenticated_user=None,
            human_interaction_callback=AsyncMock(),
            _step_adaptor=None,
            _pending_observability_trace=None,
            create_websocket_message=AsyncMock(),
        )

        await ReconnectableWebSocketMessageHandler._run_workflow(
            handler,
            payload={"query": "hello"},
        )

        handler.create_websocket_message.assert_awaited_once()
        kwargs = handler.create_websocket_message.await_args.kwargs
        payload = kwargs["data_model"]

        assert payload.code == ErrorTypes.UNKNOWN_ERROR
        assert payload.message == "auth_error"
        assert "token expired" in (payload.details or "")
        assert kwargs["message_type"] == WebSocketMessageType.ERROR_MESSAGE
        assert kwargs["status"] == WebSocketMessageStatus.COMPLETE
