# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from gsf.models import CatalogSearchResponse
from gsf.models import TextToSQLResponse
from gsf.register import GSFFunctionGroupConfig
from gsf.register import GSFPasswordAuthConfig
from gsf.register import gsf_function_group

_TEST_PASSWORD = "${TEST_GSF_PASSWORD}"


class FakeClientContext:
    def __init__(self, client: MagicMock) -> None:
        self.client = client

    async def __aenter__(self) -> MagicMock:
        return self.client

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        pass


def test_password_auth_is_optional_and_keeps_secret_wrapped() -> None:
    default_config = GSFFunctionGroupConfig(base_url="https://gsf.example")
    password_config = GSFFunctionGroupConfig(
        base_url="https://gsf.example",
        auth={
            "mode": "password",
            "email": "developer@example.com",
            "password": _TEST_PASSWORD,
        },
    )

    assert default_config.auth is None
    assert isinstance(password_config.auth, GSFPasswordAuthConfig)
    assert password_config.auth.password.get_secret_value() == _TEST_PASSWORD
    assert _TEST_PASSWORD not in repr(password_config)


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
async def test_catalog_search_resolves_token_per_invocation(catalog_search_response: dict) -> None:
    client = MagicMock()
    client.catalog_search = AsyncMock(return_value=CatalogSearchResponse.model_validate(catalog_search_response))
    config = GSFFunctionGroupConfig(base_url="https://gsf.example", include=["catalog_search"])

    with (
        patch("gsf.register.GSFClient.from_config", return_value=FakeClientContext(client)),
        patch("gsf.register.get_auth_token", return_value="token-one"),
        patch("gsf.register._request_trace_headers", return_value={}),
    ):
        async with gsf_function_group(config, MagicMock()) as group:
            tool = (await group.get_accessible_functions())["gsf__catalog_search"]
            result = json.loads(await tool.ainvoke({"question": "Find revenue metrics"}))

    assert result["request_id"] == "gsf-catalog-request-1"
    assert client.catalog_search.await_args.kwargs["token"] == "token-one"


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
    assert first["thoughts"] == "- Constructing SQL: Used quarterly_results."
    assert second["thoughts"] == "- Constructing SQL: Used quarterly_results."
    assert "response" not in first
    assert "response" not in second
    assert client.text_to_sql.await_args_list[0].kwargs["token"] == "token-one"
    assert client.text_to_sql.await_args_list[1].kwargs["token"] == "token-two"
    assert "token" not in client.__dict__


@pytest.mark.asyncio
async def test_explicit_password_auth_does_not_resolve_user_token(text_to_sql_response: dict) -> None:
    client = MagicMock()
    client.text_to_sql = AsyncMock(return_value=TextToSQLResponse.model_validate(text_to_sql_response))
    config = GSFFunctionGroupConfig(
        base_url="https://gsf.example",
        include=["text_to_sql"],
        auth={
            "mode": "password",
            "email": "developer@example.com",
            "password": _TEST_PASSWORD,
        },
    )

    with (
        patch("gsf.register.GSFClient.from_config", return_value=FakeClientContext(client)),
        patch("gsf.register.get_auth_token") as get_auth_token,
        patch("gsf.register._request_trace_headers", return_value={}),
    ):
        async with gsf_function_group(config, MagicMock()) as group:
            tool = (await group.get_accessible_functions())["gsf__text_to_sql"]
            result = json.loads(await tool.ainvoke({"question": "Show data"}))

    assert result["request_id"] == "gsf-request-1"
    get_auth_token.assert_not_called()
    assert client.text_to_sql.await_args.kwargs["token"] is None


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
