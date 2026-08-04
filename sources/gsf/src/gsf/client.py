# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Typed asynchronous client for GSF HTTP capabilities."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from typing import TypeVar

import httpx
from pydantic import BaseModel
from pydantic import ValidationError

from .errors import GSFError
from .errors import GSFErrorCode
from .models import QueryContextRequest
from .models import QueryContextResponse
from .models import TextToSQLRequest
from .models import TextToSQLResponse

ResponseT = TypeVar("ResponseT", bound=BaseModel)

_FORWARDED_HEADER_NAMES = frozenset({"baggage", "traceparent", "tracestate", "x-correlation-id", "x-request-id"})
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class GSFClient:
    """NAT-independent client sharing one bounded HTTP connection pool."""

    def __init__(
        self,
        *,
        base_url: str,
        api_version: str = "v1",
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 60.0,
        max_retries: int = 2,
        max_response_bytes: int = 5_000_000,
        default_max_rows: int = 1_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_base_url = f"{base_url.rstrip('/')}/api/{api_version.strip('/')}"
        self._max_retries = max_retries
        self._max_response_bytes = max_response_bytes
        self._default_max_rows = default_max_rows
        self._transport = transport
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_config(cls, config: Any) -> "GSFClient":
        """Construct a client from the GSF function-group config without importing NAT."""

        return cls(
            base_url=str(config.base_url),
            api_version=config.api_version,
            connect_timeout_seconds=config.connect_timeout_seconds,
            read_timeout_seconds=config.read_timeout_seconds,
            max_retries=config.max_retries,
            max_response_bytes=config.max_response_bytes,
            default_max_rows=config.default_max_rows,
        )

    async def __aenter__(self) -> "GSFClient":
        self._client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def text_to_sql(
        self,
        request: TextToSQLRequest,
        *,
        token: str,
        trace_headers: Mapping[str, str] | None = None,
    ) -> TextToSQLResponse:
        """Call GSF text-to-SQL and enforce AI-Q's configured row ceiling."""

        max_rows = min(request.max_rows, self._default_max_rows)
        payload = request.model_dump(exclude_none=True)
        payload["max_rows"] = max_rows
        result = await self._post(
            "text-to-sql",
            payload,
            response_model=TextToSQLResponse,
            token=token,
            trace_headers=trace_headers,
            capability="GSF text-to-SQL",
        )
        if len(result.rows) > max_rows:
            result.rows = result.rows[:max_rows]
            result.truncated = True
        return result

    async def query_context(
        self,
        request: QueryContextRequest,
        *,
        token: str,
        trace_headers: Mapping[str, str] | None = None,
    ) -> QueryContextResponse:
        """Call GSF query-context and validate its token-budgeted metadata."""

        return await self._post(
            "query-context",
            request.model_dump(exclude_none=True),
            response_model=QueryContextResponse,
            token=token,
            trace_headers=trace_headers,
            capability="GSF query context",
        )

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        response_model: type[ResponseT],
        token: str,
        trace_headers: Mapping[str, str] | None,
        capability: str,
    ) -> ResponseT:
        client = self._require_client()
        headers = self._build_headers(token, trace_headers)
        attempts = self._max_retries + 1

        for attempt in range(attempts):
            response: httpx.Response | None = None
            try:
                request = client.build_request(
                    "POST",
                    f"{self._api_base_url}/{endpoint}",
                    json=payload,
                    headers=headers,
                )
                response = await client.send(request, stream=True)
                request_id = response.headers.get("x-request-id")
                if response.status_code >= 400:
                    error = self._http_error(response.status_code, capability, request_id)
                    if error.retryable and attempt + 1 < attempts:
                        await response.aclose()
                        response = None
                        await asyncio.sleep(2**attempt)
                        continue
                    raise error

                body = await self._read_bounded(response, request_id=request_id)
                return self._validate_response(body, response_model, request_id=request_id)
            except GSFError:
                raise
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GSFError(
                    GSFErrorCode.TIMEOUT,
                    f"{capability} timed out.",
                    retryable=True,
                ) from exc
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GSFError(
                    GSFErrorCode.UPSTREAM_ERROR,
                    f"{capability} could not reach GSF.",
                    retryable=True,
                ) from exc
            finally:
                if response is not None:
                    await response.aclose()

        raise AssertionError("unreachable")

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GSFClient must be used as an async context manager")
        return self._client

    @staticmethod
    def _build_headers(token: str, trace_headers: Mapping[str, str] | None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        for name, value in (trace_headers or {}).items():
            if name.lower() in _FORWARDED_HEADER_NAMES and value:
                headers[name] = value
        return headers

    async def _read_bounded(self, response: httpx.Response, *, request_id: str | None) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise self._response_too_large(request_id)
            except ValueError:
                pass

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self._max_response_bytes:
                raise self._response_too_large(request_id)
        return bytes(body)

    @staticmethod
    def _validate_response(body: bytes, response_model: type[ResponseT], *, request_id: str | None) -> ResponseT:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict) and set(payload) == {"data"}:
                payload = payload["data"]
            return response_model.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as exc:
            raise GSFError(
                GSFErrorCode.INVALID_RESPONSE,
                "GSF returned an invalid response.",
                request_id=request_id,
            ) from exc

    def _response_too_large(self, request_id: str | None) -> GSFError:
        return GSFError(
            GSFErrorCode.RESPONSE_TOO_LARGE,
            "GSF response exceeded the configured size limit.",
            request_id=request_id,
        )

    @staticmethod
    def _http_error(status_code: int, capability: str, request_id: str | None) -> GSFError:
        if status_code == 401:
            return GSFError(
                GSFErrorCode.AUTHENTICATION_REQUIRED,
                "GSF authentication is required.",
                request_id=request_id,
            )
        if status_code == 403:
            return GSFError(GSFErrorCode.FORBIDDEN, "GSF access is forbidden.", request_id=request_id)
        if status_code == 404:
            return GSFError(
                GSFErrorCode.CAPABILITY_UNAVAILABLE,
                f"{capability} is unavailable.",
                request_id=request_id,
            )
        if status_code in {400, 422}:
            return GSFError(
                GSFErrorCode.INVALID_REQUEST,
                "GSF rejected the request.",
                request_id=request_id,
            )
        if status_code == 429:
            return GSFError(
                GSFErrorCode.RATE_LIMITED,
                "GSF rate limit was reached.",
                retryable=True,
                request_id=request_id,
            )
        if status_code in _RETRYABLE_STATUS_CODES:
            return GSFError(
                GSFErrorCode.UPSTREAM_ERROR,
                "GSF is temporarily unavailable.",
                retryable=True,
                request_id=request_id,
            )
        return GSFError(
            GSFErrorCode.UPSTREAM_ERROR,
            "GSF request failed.",
            request_id=request_id,
        )
