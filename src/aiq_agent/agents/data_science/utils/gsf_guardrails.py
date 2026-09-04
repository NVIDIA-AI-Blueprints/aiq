# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Request-local GSF serialization, budgets, caching, and evidence diagnostics."""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from .analysis_runtime import register_gsf_result

_CATALOG_TOOL = "gsf__catalog_search"
_SQL_TOOL = "gsf__text_to_sql"
_GSF_TOOLS = frozenset({_CATALOG_TOOL, _SQL_TOOL})


@dataclass(frozen=True, slots=True)
class GSFCallBudget:
    """Optional hard limits and exact-call caching for one agent run."""

    catalog_calls: int | None = None
    text_to_sql_calls: int | None = None
    cache_repeated_calls: bool = True


@dataclass(frozen=True, slots=True)
class GSFCallRecord:
    """Compact, non-sensitive evidence-gain diagnostic for one call."""

    tool_name: str
    status: str
    cached: bool
    row_count: int | None = None
    candidate_count: int | None = None
    coverage: float | None = None
    truncated: bool | None = None


@dataclass(slots=True)
class _GSFRunState:
    budget: GSFCallBudget
    counts: dict[str, int] = field(default_factory=lambda: {_CATALOG_TOOL: 0, _SQL_TOOL: 0})
    cache: dict[str, ToolMessage] = field(default_factory=dict)
    records: list[GSFCallRecord] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_CURRENT_GSF_RUN: ContextVar[_GSFRunState | None] = ContextVar("current_data_science_gsf_run", default=None)


def begin_gsf_run(budget: GSFCallBudget) -> Token[_GSFRunState | None]:
    """Install isolated GSF accounting for the current async request."""

    return _CURRENT_GSF_RUN.set(_GSFRunState(budget=budget))


def summarize_gsf_run() -> dict[str, Any]:
    """Return compact counters suitable for tracing and tests."""

    state = _CURRENT_GSF_RUN.get()
    if state is None:
        return {}
    return {
        "catalog_calls": state.counts[_CATALOG_TOOL],
        "text_to_sql_calls": state.counts[_SQL_TOOL],
        "cache_hits": sum(record.cached for record in state.records),
        "records": [
            {
                "tool_name": record.tool_name,
                "status": record.status,
                "cached": record.cached,
                "row_count": record.row_count,
                "candidate_count": record.candidate_count,
                "coverage": record.coverage,
                "truncated": record.truncated,
            }
            for record in state.records
        ],
    }


def end_gsf_run(token: Token[_GSFRunState | None]) -> None:
    """Restore the prior request-local GSF accounting context."""

    _CURRENT_GSF_RUN.reset(token)


def _cache_key(tool_name: str, args: Any) -> str:
    try:
        serialized = json.dumps(args, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        serialized = repr(args)
    return f"{tool_name}:{serialized}"


def _limit_for(tool_name: str, budget: GSFCallBudget) -> int | None:
    if tool_name == _CATALOG_TOOL:
        return budget.catalog_calls
    if tool_name == _SQL_TOOL:
        return budget.text_to_sql_calls
    return None


def _record_from_message(tool_name: str, message: ToolMessage, *, cached: bool) -> GSFCallRecord:
    content = str(message.content or "")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = None
    status = str(getattr(message, "status", None) or "success")
    row_count = None
    candidate_count = None
    coverage = None
    truncated = None
    if isinstance(payload, dict):
        status = str(payload.get("status") or status)
        rows = payload.get("rows")
        candidates = payload.get("candidates")
        row_count = len(rows) if isinstance(rows, list) else None
        candidate_count = len(candidates) if isinstance(candidates, list) else None
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), (int, float)) else None
        truncated = payload.get("truncated") if isinstance(payload.get("truncated"), bool) else None
    return GSFCallRecord(
        tool_name=tool_name,
        status=status,
        cached=cached,
        row_count=row_count,
        candidate_count=candidate_count,
        coverage=coverage,
        truncated=truncated,
    )


def _register_sql_evidence(tool_call: dict[str, Any], message: ToolMessage) -> ToolMessage:
    """Persist exact SQL rows for Python and annotate the model-facing receipt."""

    try:
        payload = json.loads(str(message.content or ""))
    except json.JSONDecodeError:
        return message
    if not isinstance(payload, dict):
        return message
    args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
    reference = register_gsf_result(
        question=str(args.get("question") or ""),
        database_name=str(args["database_name"]) if args.get("database_name") is not None else None,
        payload=payload,
    )
    if reference is None:
        return message
    payload["analysis_ref"] = reference
    payload["analysis_hint"] = (
        f"Use gsf_rows('{reference}') in the Python tool to load these exact rows; do not copy them manually."
    )
    try:
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return message
    return message.model_copy(update={"content": content})


class GSFCallGuardMiddleware(AgentMiddleware):
    """Serialize GSF calls and enforce request-local hard limits and exact caching."""

    def __init__(self, budget: GSFCallBudget) -> None:
        self.budget = budget

    async def awrap_tool_call(self, request, handler):
        """Guard one GSF call while leaving every non-GSF tool unchanged."""

        tool_call = request.tool_call if isinstance(request.tool_call, dict) else {}
        tool_name = tool_call.get("name")
        if tool_name not in _GSF_TOOLS:
            return await handler(request)

        run_state = _CURRENT_GSF_RUN.get()
        if run_state is None:
            return await handler(request)

        async with run_state.lock:
            cache_key = _cache_key(tool_name, tool_call.get("args"))
            if run_state.budget.cache_repeated_calls and cache_key in run_state.cache:
                cached = run_state.cache[cache_key].model_copy(
                    update={"tool_call_id": tool_call.get("id", "gsf-cache-hit"), "name": tool_name}
                )
                run_state.records.append(_record_from_message(tool_name, cached, cached=True))
                return cached

            limit = _limit_for(tool_name, run_state.budget)
            used = run_state.counts[tool_name]
            if limit is not None and used >= limit:
                blocked = ToolMessage(
                    content=json.dumps(
                        {
                            "status": "error",
                            "code": "aiq_gsf_call_budget_exhausted",
                            "message": (
                                f"The request-local {tool_name} limit of {limit} has been reached. "
                                "Use collected evidence and synthesize a bounded answer."
                            ),
                            "retryable": False,
                        },
                        separators=(",", ":"),
                    ),
                    tool_call_id=tool_call.get("id", "gsf-budget-exhausted"),
                    name=tool_name,
                    status="error",
                )
                run_state.records.append(
                    GSFCallRecord(
                        tool_name=tool_name,
                        status="budget_exhausted",
                        cached=False,
                    )
                )
                return blocked

            run_state.counts[tool_name] += 1
            result = await handler(request)
            if isinstance(result, ToolMessage):
                if tool_name == _SQL_TOOL:
                    result = _register_sql_evidence(tool_call, result)
                record = _record_from_message(tool_name, result, cached=False)
                run_state.records.append(record)
                if run_state.budget.cache_repeated_calls and record.status != "error":
                    run_state.cache[cache_key] = result
            return result


__all__ = [
    "GSFCallBudget",
    "GSFCallGuardMiddleware",
    "begin_gsf_run",
    "end_gsf_run",
    "summarize_gsf_run",
]
