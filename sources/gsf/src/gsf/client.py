# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Typed asynchronous client for GSF HTTP capabilities."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from .errors import GSFError
from .errors import GSFErrorCode
from .models import ChatCompletionResult
from .models import ChatCompletionsRequest
from .models import ResultColumn
from .models import TextToSQLRequest
from .models import TextToSQLResponse

_FORWARDED_HEADER_NAMES = frozenset({"baggage", "traceparent", "tracestate", "x-correlation-id", "x-request-id"})
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class GSFClient:
    """NAT-independent client sharing one bounded HTTP connection pool."""

    def __init__(
        self,
        *,
        base_url: str,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 60.0,
        max_retries: int = 2,
        max_response_bytes: int = 5_000_000,
        default_max_rows: int = 1_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_base_url = f"{base_url.rstrip('/')}/api"
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
        """Run the SQL branch of GSF chat completions and normalize its answer."""

        max_rows = min(request.max_rows, self._default_max_rows)
        result = await self.chat_completions(
            ChatCompletionsRequest(
                question=request.question,
                prediction=False,
                target_db=request.database_name,
            ),
            token=token,
            trace_headers=trace_headers,
        )
        return self._normalize_text_to_sql(result, max_rows=max_rows)

    async def chat_completions(
        self,
        request: ChatCompletionsRequest,
        *,
        token: str,
        trace_headers: Mapping[str, str] | None = None,
    ) -> ChatCompletionResult:
        """Call the shared GSF chat endpoint and extract its final SSE result."""

        body, request_id, content_type = await self._post(
            "chat/completions",
            request.model_dump(exclude_none=True),
            token=token,
            trace_headers=trace_headers,
            capability="GSF chat completions",
            accept="text/event-stream",
        )
        answer = self._parse_chat_answer(body, content_type=content_type, request_id=request_id)
        return ChatCompletionResult(answer=answer, request_id=request_id)

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        token: str,
        trace_headers: Mapping[str, str] | None,
        capability: str,
        accept: str = "application/json",
    ) -> tuple[bytes, str | None, str]:
        client = self._require_client()
        headers = self._build_headers(token, trace_headers, accept=accept)
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
                return body, request_id, response.headers.get("content-type", "")
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
    def _build_headers(
        token: str,
        trace_headers: Mapping[str, str] | None,
        *,
        accept: str,
    ) -> dict[str, str]:
        headers = {
            "Accept": accept,
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

    @classmethod
    def _parse_chat_answer(cls, body: bytes, *, content_type: str, request_id: str | None) -> dict[str, Any]:
        try:
            text = body.decode("utf-8")
            if "text/event-stream" not in content_type and not text.lstrip().startswith(("data:", ":")):
                payload = json.loads(text)
                return cls._answer_from_event(payload, request_id=request_id)

            data_lines: list[str] = []
            for line in [*text.splitlines(), ""]:
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                    continue
                if line or not data_lines:
                    continue
                event_data = "\n".join(data_lines)
                data_lines.clear()
                if event_data == "[DONE]":
                    continue
                event = json.loads(event_data)
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "error":
                    raise GSFError(
                        GSFErrorCode.UPSTREAM_ERROR,
                        "GSF chat completions failed.",
                        request_id=request_id,
                    )
                if event.get("type") == "result":
                    return cls._answer_from_event(event, request_id=request_id)
        except GSFError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise GSFError(
                GSFErrorCode.INVALID_RESPONSE,
                "GSF returned an invalid response.",
                request_id=request_id,
            ) from exc

        raise GSFError(
            GSFErrorCode.INVALID_RESPONSE,
            "GSF response did not contain a final result.",
            request_id=request_id,
        )

    @staticmethod
    def _answer_from_event(payload: Any, *, request_id: str | None) -> dict[str, Any]:
        if isinstance(payload, dict) and isinstance(payload.get("answer"), dict):
            return payload["answer"]
        if isinstance(payload, dict) and payload.get("type") is None:
            return payload
        raise GSFError(
            GSFErrorCode.INVALID_RESPONSE,
            "GSF returned an invalid final answer.",
            request_id=request_id,
        )

    @classmethod
    def _normalize_text_to_sql(cls, result: ChatCompletionResult, *, max_rows: int) -> TextToSQLResponse:
        answer = result.answer
        sql = answer.get("sql") or answer.get("sql_code")
        if not isinstance(sql, str) or not sql.strip():
            raise GSFError(
                GSFErrorCode.INVALID_RESPONSE,
                "GSF did not return validated SQL.",
                request_id=result.request_id,
            )

        rows = cls._normalize_rows(answer.get("rows", answer.get("sql_response_from_db")), result.request_id)
        upstream_truncated = bool(answer.get("truncated", False))
        truncated = upstream_truncated or len(rows) > max_rows
        rows = rows[:max_rows]
        columns = cls._normalize_columns(answer.get("columns", answer.get("sql_columns")))
        if not columns and rows:
            columns = [ResultColumn(name=str(name)) for name in rows[0]]

        try:
            return TextToSQLResponse(
                request_id=answer.get("request_id") or result.request_id,
                response=answer.get("response"),
                sql=sql,
                columns=columns,
                rows=rows,
                truncated=truncated,
                custom_analyses_used=answer.get("custom_analyses_used"),
                objects_used=answer.get("objects_used"),
                joins_used=answer.get("joins_used"),
                semantic_context=answer.get("semantic_context"),
                validation_attempts=answer.get("validation_attempts"),
                assumptions=answer.get("assumptions"),
                warnings=answer.get("warnings"),
                timings=answer.get("timings"),
            )
        except ValidationError as exc:
            raise GSFError(
                GSFErrorCode.INVALID_RESPONSE,
                "GSF returned invalid text-to-SQL data.",
                request_id=result.request_id,
            ) from exc

    @staticmethod
    def _normalize_columns(value: Any) -> list[ResultColumn]:
        if not isinstance(value, list):
            return []
        columns: list[ResultColumn] = []
        for column in value:
            if isinstance(column, dict):
                name = column.get("name") or column.get("column_name") or column.get("id")
                if name is not None:
                    columns.append(
                        ResultColumn(
                            name=str(name),
                            data_type=column.get("data_type") or column.get("type"),
                        )
                    )
            elif column is not None:
                columns.append(ResultColumn(name=str(column)))
        return columns

    @staticmethod
    def _normalize_rows(value: Any, request_id: str | None) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise GSFError(
                    GSFErrorCode.INVALID_RESPONSE,
                    "GSF returned invalid query rows.",
                    request_id=request_id,
                ) from exc
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, list):
            raise GSFError(
                GSFErrorCode.INVALID_RESPONSE,
                "GSF returned invalid query rows.",
                request_id=request_id,
            )

        rows: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                rows.append(item)
                continue
            if isinstance(item, str):
                try:
                    parsed = json.loads(item)
                except json.JSONDecodeError as exc:
                    raise GSFError(
                        GSFErrorCode.INVALID_RESPONSE,
                        "GSF returned invalid query rows.",
                        request_id=request_id,
                    ) from exc
                if isinstance(parsed, dict):
                    rows.append(parsed)
                elif isinstance(parsed, list) and all(isinstance(row, dict) for row in parsed):
                    rows.extend(parsed)
                else:
                    raise GSFError(
                        GSFErrorCode.INVALID_RESPONSE,
                        "GSF returned invalid query rows.",
                        request_id=request_id,
                    )
            else:
                raise GSFError(
                    GSFErrorCode.INVALID_RESPONSE,
                    "GSF returned invalid query rows.",
                    request_id=request_id,
                )
        return rows

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
