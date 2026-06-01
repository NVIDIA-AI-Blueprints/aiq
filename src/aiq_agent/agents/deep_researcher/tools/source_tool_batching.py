# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Batch wrappers for researcher-facing source tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..custom_middleware import SourceToolConcurrencyLimiter


class BatchSourceToolInput(BaseModel):
    """Input schema for batch-capable same-name source tool wrappers."""

    model_config = ConfigDict(extra="forbid")

    queries: str | list[str] = Field(description="One query/input string, or a list of query/input strings.")


@dataclass(frozen=True)
class BatchToolBuildResult:
    """Researcher-facing tools plus names of source tools wrapped for batching."""

    tools: list[BaseTool]
    wrapped_tool_names: set[str]


def _single_string_input_field(tool: BaseTool) -> str | None:
    """Return the sole string input field for a compatible tool, otherwise None."""
    schema = getattr(tool, "args_schema", None)
    fields = getattr(schema, "model_fields", None)
    if not fields or len(fields) != 1:
        return None

    name, field = next(iter(fields.items()))
    if field.annotation is str:
        return name
    return None


def _format_batch_tool_output(results: list[tuple[str, str | None, str | None]]) -> str:
    """Render grouped per-input output without hiding partial failures."""
    parts: list[str] = []
    for query, output, error in results:
        body = f"ERROR: {error}" if error else (output or "")
        parts.append(f"## Query: {query}\n{body}")
    return "\n\n---\n\n".join(parts)


def _make_batch_source_tool(
    original_tool: BaseTool,
    *,
    input_field_name: str,
    limiter: SourceToolConcurrencyLimiter,
    max_batch_size: int,
) -> BaseTool:
    """Create a same-name wrapper that fans out list input to the original tool."""

    async def _run_batch(queries: str | list[str]) -> str:
        query_list = [queries] if isinstance(queries, str) else list(queries)
        if not query_list:
            return "No queries provided."
        if len(query_list) > max_batch_size:
            return (
                f"ERROR: {original_tool.name} accepts at most {max_batch_size} queries per batch. "
                f"Received {len(query_list)}."
            )

        async def _call_one(query: str) -> tuple[str, str | None, str | None]:
            try:
                async with limiter.limit():
                    result = await original_tool.ainvoke({input_field_name: query})
                return query, str(result), None
            except Exception as exc:  # noqa: BLE001 - represented as per-item failure for the LLM
                return query, None, str(exc)

        results = await asyncio.gather(*(_call_one(query) for query in query_list))
        return _format_batch_tool_output(results)

    description = (
        f"{original_tool.description}\n\n"
        "Batch mode: pass `queries` as either a single string or a list of strings. "
        "Each item is run as one underlying source-tool call and returned in grouped sections."
    )
    return StructuredTool.from_function(
        coroutine=_run_batch,
        name=original_tool.name,
        description=description,
        args_schema=BatchSourceToolInput,
    )


def build_batch_source_tools(
    tools: list[BaseTool],
    *,
    source_tool_names: set[str],
    limiter: SourceToolConcurrencyLimiter,
    max_batch_size: int,
) -> BatchToolBuildResult:
    """Wrap compatible single-string source tools with same-name batch-capable tools."""
    wrapped_tools: list[BaseTool] = []
    wrapped_tool_names: set[str] = set()

    for candidate in tools:
        input_field_name = None
        if candidate.name in source_tool_names:
            input_field_name = _single_string_input_field(candidate)

        if input_field_name is None:
            wrapped_tools.append(candidate)
            continue

        wrapped_tools.append(
            _make_batch_source_tool(
                candidate,
                input_field_name=input_field_name,
                limiter=limiter,
                max_batch_size=max_batch_size,
            )
        )
        wrapped_tool_names.add(candidate.name)

    return BatchToolBuildResult(tools=wrapped_tools, wrapped_tool_names=wrapped_tool_names)
