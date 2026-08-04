# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import AsyncMock
from unittest.mock import patch

import httpx
import pytest
from gsf.client import GSFClient
from gsf.errors import GSFError
from gsf.errors import GSFErrorCode
from gsf.models import QueryContextRequest
from gsf.models import TextToSQLRequest


@pytest.mark.asyncio
async def test_text_to_sql_sends_scoped_request_and_bounds_rows(text_to_sql_response: dict) -> None:
    seen_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json=text_to_sql_response, headers={"x-request-id": "header-request"})

    client = GSFClient(
        base_url="https://gsf.example",
        default_max_rows=1,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        result = await client.text_to_sql(
            TextToSQLRequest(question="Show revenue", database_name="benchmark_db", max_rows=20),
            token="user-token",
            trace_headers={"traceparent": "00-trace", "authorization": "do-not-forward"},
        )

    assert seen_request is not None
    assert seen_request.url == "https://gsf.example/api/v1/text-to-sql"
    assert seen_request.headers["authorization"] == "Bearer user-token"
    assert seen_request.headers["traceparent"] == "00-trace"
    assert json.loads(seen_request.content) == {
        "question": "Show revenue",
        "database_name": "benchmark_db",
        "execute": True,
        "object_ids": [],
        "max_rows": 1,
    }
    assert result.rows == [{"revenue": 100}]
    assert result.truncated is True


@pytest.mark.asyncio
async def test_query_context_omits_database_and_unwraps_data(query_context_response: dict) -> None:
    seen_payload: dict | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload
        seen_payload = json.loads(request.content)
        return httpx.Response(200, json={"data": query_context_response})

    client = GSFClient(base_url="https://gsf.example/", transport=httpx.MockTransport(handler))
    async with client:
        result = await client.query_context(
            QueryContextRequest(question="What revenue data is available?", token_budget=2_000),
            token="user-token",
        )

    assert seen_payload == {
        "question": "What revenue data is available?",
        "object_ids": [],
        "token_budget": 2_000,
    }
    assert result.request_id == "gsf-request-2"


@pytest.mark.asyncio
async def test_client_normalizes_forbidden_without_leaking_body() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="secret database details")

    client = GSFClient(base_url="https://gsf.example", transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(GSFError) as raised:
            await client.query_context(QueryContextRequest(question="Show data"), token="user-token")

    assert raised.value.code is GSFErrorCode.FORBIDDEN
    assert "secret" not in raised.value.message


@pytest.mark.asyncio
async def test_client_retries_rate_limit_then_succeeds(query_context_response: dict) -> None:
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=query_context_response)

    client = GSFClient(base_url="https://gsf.example", max_retries=1, transport=httpx.MockTransport(handler))
    with patch("gsf.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
        async with client:
            await client.query_context(QueryContextRequest(question="Show data"), token="user-token")

    assert attempts == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_client_rejects_oversized_response(query_context_response: dict) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=query_context_response)

    client = GSFClient(
        base_url="https://gsf.example",
        max_response_bytes=10,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        with pytest.raises(GSFError) as raised:
            await client.query_context(QueryContextRequest(question="Show data"), token="user-token")

    assert raised.value.code is GSFErrorCode.RESPONSE_TOO_LARGE


@pytest.mark.asyncio
async def test_client_rejects_malformed_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = GSFClient(base_url="https://gsf.example", transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(GSFError) as raised:
            await client.query_context(QueryContextRequest(question="Show data"), token="user-token")

    assert raised.value.code is GSFErrorCode.INVALID_RESPONSE
