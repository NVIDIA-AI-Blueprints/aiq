# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from gsf.models import TextToSQLResponse
from gsf.register import GSFFunctionGroupConfig
from gsf.register import gsf_function_group


class FakeClientContext:
    def __init__(self, client: MagicMock) -> None:
        self.client = client

    async def __aenter__(self) -> MagicMock:
        return self.client

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None


@pytest.mark.asyncio
async def test_group_exposes_only_requested_tools(text_to_sql_response: dict) -> None:
    client = MagicMock()
    client.text_to_sql = AsyncMock(return_value=TextToSQLResponse.model_validate(text_to_sql_response))
    config = GSFFunctionGroupConfig(base_url="https://gsf.example", include=["text_to_sql"])

    with patch("gsf.register.GSFClient.from_config", return_value=FakeClientContext(client)):
        async with gsf_function_group(config, MagicMock()) as group:
            tools = await group.get_accessible_functions()

    assert set(tools) == {"gsf__text_to_sql"}


@pytest.mark.asyncio
async def test_text_to_sql_resolves_token_per_invocation(text_to_sql_response: dict) -> None:
    client = MagicMock()
    client.text_to_sql = AsyncMock(return_value=TextToSQLResponse.model_validate(text_to_sql_response))
    config = GSFFunctionGroupConfig(base_url="https://gsf.example", include=["text_to_sql"])

    with (
        patch("gsf.register.GSFClient.from_config", return_value=FakeClientContext(client)),
        patch("gsf.register.get_auth_token", side_effect=["token-one", "token-two"]),
        patch("gsf.register._request_trace_headers", return_value={}),
    ):
        async with gsf_function_group(config, MagicMock()) as group:
            tool = (await group.get_accessible_functions())["gsf__text_to_sql"]
            first = json.loads(await tool.ainvoke({"question": "First question"}))
            second = json.loads(await tool.ainvoke({"question": "Second question"}))

    assert first["request_id"] == "gsf-request-1"
    assert second["request_id"] == "gsf-request-1"
    assert client.text_to_sql.await_args_list[0].kwargs["token"] == "token-one"
    assert client.text_to_sql.await_args_list[1].kwargs["token"] == "token-two"
    assert "token" not in client.__dict__


@pytest.mark.asyncio
async def test_missing_authentication_fails_closed() -> None:
    client = MagicMock()
    client.text_to_sql = AsyncMock()
    config = GSFFunctionGroupConfig(base_url="https://gsf.example", include=["text_to_sql"])

    with (
        patch("gsf.register.GSFClient.from_config", return_value=FakeClientContext(client)),
        patch("gsf.register.get_auth_token", return_value=None),
    ):
        async with gsf_function_group(config, MagicMock()) as group:
            tool = (await group.get_accessible_functions())["gsf__text_to_sql"]
            result = json.loads(await tool.ainvoke({"question": "Show data"}))

    assert result["code"] == "authentication_required"
    client.text_to_sql.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "tool_input", "message"),
    [
        ("catalog_search", {"question": "Find revenue metrics"}, "GSF catalog search is unavailable."),
        ("query_context", {"question": "Show data"}, "GSF query context is unavailable."),
    ],
)
async def test_placeholder_tools_are_explicitly_unavailable(tool_name: str, tool_input: dict, message: str) -> None:
    client = MagicMock()
    config = GSFFunctionGroupConfig(base_url="https://gsf.example", include=[tool_name])

    with patch("gsf.register.GSFClient.from_config", return_value=FakeClientContext(client)):
        async with gsf_function_group(config, MagicMock()) as group:
            tool = (await group.get_accessible_functions())[f"gsf__{tool_name}"]
            result = json.loads(await tool.ainvoke(tool_input))

    assert result == {
        "status": "error",
        "code": "capability_unavailable",
        "retryable": False,
        "message": message,
    }
