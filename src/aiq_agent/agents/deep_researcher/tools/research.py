# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Researcher runnable and batched research tool construction."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from typing import cast

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import render_prompt_template

from ..models import DeepResearchAgentState
from ..models import ResearchBatchItemResult
from ..models import ResearchBatchResult
from ..models import ResearchNotes
from ..models import ResearchQuery

_NO_TOOL_RUNTIME = cast(ToolRuntime, None)


def render_researcher_prompt(
    *,
    prompt_template: str,
    state: DeepResearchAgentState,
    tools_info: list[dict[str, str]],
    current_datetime: str,
) -> str:
    """Render researcher instructions from the current request context."""
    available_docs = [doc.model_dump() for doc in (state.available_documents or [])]
    return render_prompt_template(
        prompt_template,
        current_datetime=current_datetime,
        user_info=state.user_info,
        tools=tools_info,
        available_documents=available_docs,
    )


def build_researcher_runnable(
    llm_provider: LLMProvider,
    state: DeepResearchAgentState,
    prompt_template: str,
    tools_info: list[dict[str, str]],
    current_datetime: str,
    researcher_tools: list[BaseTool],
    researcher_middleware: list[Any],
    skill_sources: list[str] | None = None,
    backend: Any = None,
) -> Any:
    """Build the reusable single-query researcher runnable."""
    researcher_model = llm_provider.get(LLMRole.RESEARCHER)
    middleware: list[Any] = [TodoListMiddleware()]
    if skill_sources:
        middleware.append(SkillsMiddleware(backend=backend, sources=skill_sources))
    middleware.append(FilesystemMiddleware(backend=backend))
    middleware.extend(
        [
            create_summarization_middleware(researcher_model, backend),
            PatchToolCallsMiddleware(),
        ]
    )
    middleware.extend(researcher_middleware)

    return create_agent(
        model=researcher_model,
        tools=researcher_tools,
        system_prompt=render_researcher_prompt(
            prompt_template=prompt_template,
            state=state,
            tools_info=tools_info,
            current_datetime=current_datetime,
        ),
        middleware=middleware,
        response_format=ResearchNotes,
    )


def format_research_request(query: ResearchQuery) -> str:
    """Create the single-query researcher task text used by the batch tool."""
    query_json = json.dumps(query.model_dump(mode="json"), indent=2, ensure_ascii=False)
    return (
        "Execute this planned research query and return a ResearchNotes structured response.\n\n"
        "Execution order:\n"
        "1. Use the ResearchQuery.tool value as the source tool name. Do not substitute another source tool.\n"
        "2. Run the main ResearchQuery.query first to establish broad context.\n"
        "3. Then run each ResearchQuery.subqueries item in order. Treat every subquery as required coverage.\n"
        "4. In ResearchNotes.findings and narrative_notes, synthesize across the main query and every subquery. "
        "If a subquery cannot be answered, record it in ResearchNotes.gaps.\n\n"
        "Evidence discipline:\n"
        "- Do not answer from model memory.\n"
        "- Every ResearchFinding must be grounded in results returned by the required source tool.\n"
        "- If the source tool does not provide support for a claim, record a ResearchGap instead.\n"
        "- Do not fill missing facts from prior knowledge.\n\n"
        "Important: do not write filesystem artifacts for this batch invocation. "
        "The run_research_batch tool will persist your structured response to /shared/.\n\n"
        "ResearchQuery JSON:\n"
        f"{query_json}"
    )


def research_note_path(index: int, note: ResearchNotes) -> str:
    """Return a stable virtual filesystem path for a ResearchNotes artifact."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", note.query_topic.strip()).strip("._-").lower()
    if not slug:
        slug = "research_notes"
    return f"/shared/{index:02d}_{slug[:80]}.json"


def researcher_invoke_state(query: ResearchQuery, runtime: ToolRuntime | None) -> dict[str, Any]:
    """Build nested researcher state, carrying parent files for StateBackend-backed skills."""
    invoke_state: dict[str, Any] = {
        "messages": [HumanMessage(content=format_research_request(query))],
    }
    parent_state = getattr(runtime, "state", None) if runtime is not None else None
    if isinstance(parent_state, dict) and "files" in parent_state:
        invoke_state["files"] = parent_state["files"]
    return invoke_state


def _empty_batch_result() -> ResearchBatchResult:
    """Return the successful empty-batch result."""
    return ResearchBatchResult(
        status="succeeded",
        total=0,
        succeeded=0,
        failed=0,
        timed_out=0,
        files=[],
        results=[],
    )


def _rejected_batch_result(queries: list[ResearchQuery], error: str) -> ResearchBatchResult:
    """Return a structured batch rejection without launching researchers."""
    total = len(queries)
    return ResearchBatchResult(
        status="rejected",
        total=total,
        succeeded=0,
        failed=total,
        timed_out=0,
        files=[],
        results=[
            ResearchBatchItemResult(
                query=query,
                status="rejected",
                error=error,
                elapsed_seconds=0.0,
            )
            for query in queries
        ],
        error=error,
    )


_BROAD_QUERY_TERMS = (
    "overview",
    "survey",
    "landscape",
    "state of",
    "comprehensive",
    "taxonomy",
    "trends",
    "applications",
    "challenges",
    "risks",
    "benefits",
)


def _empty_subqueries_need_revision(query: ResearchQuery) -> bool:
    """Return True when a ResearchQuery is too broad to execute without subqueries."""
    if query.subqueries:
        return False
    if len(query.target_components) > 1:
        return True
    query_text = query.query.lower()
    return any(term in query_text for term in _BROAD_QUERY_TERMS)


def _validate_research_batch_queries(
    queries: list[ResearchQuery],
    *,
    max_batch_research_queries: int,
    source_tool_names: set[str],
) -> str | None:
    """Validate that planned ResearchQuery objects are executable."""
    total = len(queries)
    if total > max_batch_research_queries:
        return (
            f"run_research_batch accepts at most {max_batch_research_queries} curated queries. "
            f"Received {total}. Rank, merge, or drop lower-priority queries and call again."
        )

    invalid_tools = sorted({query.tool for query in queries if query.tool not in source_tool_names})
    if invalid_tools:
        available = ", ".join(sorted(source_tool_names)) or "(none)"
        invalid = ", ".join(invalid_tools)
        return (
            "run_research_batch received non-executable tool name(s): "
            f"{invalid}. Use exact available source tool names only: {available}. "
            "Do not use category labels like 'external', 'internal', 'web', or 'search'."
        )

    broad_without_subqueries = [query.query for query in queries if _empty_subqueries_need_revision(query)]
    if broad_without_subqueries:
        examples = "; ".join(broad_without_subqueries[:3])
        return (
            "run_research_batch received broad ResearchQuery item(s) with empty subqueries: "
            f"{examples}. Add 2-5 concrete ordered subqueries for each broad or multi-component query, "
            "or narrow the main query so it has one obvious search angle."
        )

    return None


async def _run_research_query(
    *,
    query: ResearchQuery,
    researcher_runnable: Any,
    runtime: ToolRuntime | None,
    callbacks: list[Any],
    timeout_seconds: float,
    semaphore: asyncio.Semaphore,
) -> ResearchBatchItemResult:
    """Run one researcher worker with timeout and structured error handling."""
    started = time.perf_counter()
    async with semaphore:
        try:
            result = await asyncio.wait_for(
                researcher_runnable.ainvoke(
                    researcher_invoke_state(query, runtime),
                    config={"callbacks": callbacks} if callbacks else None,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return ResearchBatchItemResult(
                query=query,
                status="timed_out",
                error=f"researcher worker timed out after {timeout_seconds:g} seconds",
                elapsed_seconds=time.perf_counter() - started,
            )
        except Exception as exc:  # noqa: BLE001 - captured as per-item failure
            return ResearchBatchItemResult(
                query=query,
                status="failed",
                error=str(exc),
                elapsed_seconds=time.perf_counter() - started,
            )

        try:
            structured = result.get("structured_response") if isinstance(result, dict) else None
            if structured is None:
                raise ValueError("researcher worker did not return structured ResearchNotes")
            note = ResearchNotes.model_validate(structured)
        except Exception as exc:  # noqa: BLE001 - captured as per-item failure
            return ResearchBatchItemResult(
                query=query,
                status="failed",
                error=str(exc),
                elapsed_seconds=time.perf_counter() - started,
            )

        return ResearchBatchItemResult(
            query=query,
            status="succeeded",
            note=note,
            elapsed_seconds=time.perf_counter() - started,
        )


async def _run_research_queries(
    *,
    queries: list[ResearchQuery],
    researcher_runnable: Any,
    runtime: ToolRuntime | None,
    callbacks: list[Any],
    timeout_seconds: float,
    max_concurrency: int,
) -> list[ResearchBatchItemResult]:
    """Run researcher workers concurrently with per-item failure isolation."""
    semaphore = asyncio.Semaphore(min(max_concurrency, len(queries)))
    raw_results = await asyncio.gather(
        *(
            _run_research_query(
                query=query,
                researcher_runnable=researcher_runnable,
                runtime=runtime,
                callbacks=callbacks,
                timeout_seconds=timeout_seconds,
                semaphore=semaphore,
            )
            for query in queries
        ),
        return_exceptions=True,
    )

    item_results: list[ResearchBatchItemResult] = []
    for query, raw_result in zip(queries, raw_results, strict=False):
        if isinstance(raw_result, BaseException):
            item_results.append(
                ResearchBatchItemResult(
                    query=query,
                    status="failed",
                    error=str(raw_result),
                    elapsed_seconds=0.0,
                )
            )
        else:
            item_results.append(raw_result)
    return item_results


def _successful_note_files(item_results: list[ResearchBatchItemResult]) -> tuple[list[tuple[str, bytes]], list[int]]:
    """Build upload payloads for successful notes and return matching item indexes."""
    files: list[tuple[str, bytes]] = []
    indexes: list[int] = []
    for index, item in enumerate(item_results):
        if item.status != "succeeded" or item.note is None:
            continue
        path = research_note_path(index, item.note)
        files.append((path, item.note.model_dump_json(indent=2).encode("utf-8")))
        indexes.append(index)
    return files, indexes


def _persist_successful_notes(item_results: list[ResearchBatchItemResult], backend: Any) -> None:
    """Persist successful notes and mark items failed when persistence fails."""
    files, successful_indexes = _successful_note_files(item_results)
    if not files:
        return

    try:
        upload_results = backend.upload_files(files)
        for offset, item_index in enumerate(successful_indexes):
            if offset >= len(upload_results):
                item_results[item_index].status = "failed"
                item_results[item_index].error = "Failed to write research note file: missing upload result"
                item_results[item_index].file_path = None
                continue
            upload_result = upload_results[offset]
            if upload_result.error:
                item_results[item_index].status = "failed"
                item_results[item_index].error = upload_result.error
                item_results[item_index].file_path = None
            else:
                item_results[item_index].file_path = upload_result.path
    except Exception as exc:  # noqa: BLE001 - preserve researcher outputs but mark persistence failures
        for item_index in successful_indexes:
            item_results[item_index].status = "failed"
            item_results[item_index].error = f"Failed to write research note file: {exc}"
            item_results[item_index].file_path = None


def _build_batch_result(total: int, item_results: list[ResearchBatchItemResult]) -> ResearchBatchResult:
    """Build the aggregate batch result from per-query outcomes."""
    files = [item.file_path for item in item_results if item.status == "succeeded" and item.file_path]
    succeeded = sum(1 for item in item_results if item.status == "succeeded")
    timed_out = sum(1 for item in item_results if item.status == "timed_out")
    failed = total - succeeded - timed_out
    if succeeded == total:
        status = "succeeded"
    elif succeeded > 0:
        status = "partial"
    else:
        status = "failed"

    return ResearchBatchResult(
        status=status,
        total=total,
        succeeded=succeeded,
        failed=failed,
        timed_out=timed_out,
        files=files,
        results=item_results,
    )


def _compact_batch_result(batch_result: ResearchBatchResult) -> ResearchBatchResult:
    """Drop inline successful notes from batch summaries after notes are persisted to files."""
    compact_results = [
        item.model_copy(update={"note": None}) if item.note is not None else item for item in batch_result.results
    ]
    return batch_result.model_copy(update={"results": compact_results})


def _persist_batch_summary(batch_result: ResearchBatchResult, backend: Any) -> None:
    """Persist the aggregate batch result, recording summary upload failures on the result."""
    try:
        summary_uploads = backend.upload_files(
            [
                (
                    "/shared/research_batch_result.json",
                    batch_result.model_dump_json(indent=2).encode("utf-8"),
                )
            ]
        )
        summary_errors = [upload.error for upload in summary_uploads if upload.error]
        if summary_errors:
            batch_result.error = f"Failed to write batch summary: {summary_errors}"
    except Exception as exc:  # noqa: BLE001 - return the batch result even if summary persistence fails
        batch_result.error = f"Failed to write batch summary: {exc}"


def build_research_batch_tool(
    *,
    researcher_runnable: Any,
    callbacks: list[Any],
    backend: Any,
    source_tool_names: set[str],
    max_batch_research_queries: int,
    max_research_concurrency: int,
    research_query_timeout_seconds: float,
) -> BaseTool:
    """Build an orchestrator-only tool that runs researcher tasks concurrently."""

    @tool
    async def run_research_batch(
        queries: list[ResearchQuery],
        runtime: ToolRuntime = _NO_TOOL_RUNTIME,
    ) -> str:
        """Run planned research queries in parallel and write ResearchNotes JSON files."""
        total = len(queries)
        if not queries:
            return _empty_batch_result().model_dump_json()

        rejection_error = _validate_research_batch_queries(
            queries,
            max_batch_research_queries=max_batch_research_queries,
            source_tool_names=source_tool_names,
        )
        if rejection_error is not None:
            return _rejected_batch_result(queries, rejection_error).model_dump_json()

        item_results = await _run_research_queries(
            queries=queries,
            researcher_runnable=researcher_runnable,
            runtime=runtime,
            callbacks=callbacks,
            timeout_seconds=research_query_timeout_seconds,
            max_concurrency=max_research_concurrency,
        )
        _persist_successful_notes(item_results, backend)
        batch_result = _compact_batch_result(_build_batch_result(total, item_results))
        _persist_batch_summary(batch_result, backend)

        return batch_result.model_dump_json()

    return run_research_batch
