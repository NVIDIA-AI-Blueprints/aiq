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

"""Researcher runnable and batched research tool construction."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any
from typing import cast

from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from ..models import ResearchNotes
from ..models import ResearchQuery

_NO_TOOL_RUNTIME = cast(ToolRuntime, None)
logger = logging.getLogger(__name__)
_NOTE_SLUG_MAX_LENGTH = 64


def format_research_request(query: ResearchQuery) -> str:
    """Create the single-query researcher task text used by the batch tool."""
    query_json = json.dumps(query.model_dump(mode="json"), indent=2, ensure_ascii=False)
    return (
        "Batch research invocation. Execute this ResearchQuery and return a structured ResearchNotes response. "
        "Do not call write_file or edit_file; run_research_batch will persist the returned ResearchNotes under "
        "/shared/ after you return.\n\n"
        "ResearchQuery JSON:\n"
        f"{query_json}"
    )


def researcher_invoke_state(query: ResearchQuery, runtime: ToolRuntime | None) -> dict[str, Any]:
    """Build nested researcher state, carrying parent files for StateBackend-backed skills."""
    invoke_state: dict[str, Any] = {
        "messages": [HumanMessage(content=format_research_request(query))],
    }
    parent_state = getattr(runtime, "state", None) if runtime is not None else None
    if isinstance(parent_state, dict) and "files" in parent_state:
        invoke_state["files"] = parent_state["files"]
    return invoke_state


async def _run_research_query(
    *,
    query: ResearchQuery,
    researcher_runnable: Any,
    runtime: ToolRuntime | None,
    callbacks: list[Any],
    semaphore: asyncio.Semaphore,
) -> ResearchNotes:
    """Run one researcher worker and return its structured notes."""
    async with semaphore:
        try:
            result = await researcher_runnable.ainvoke(
                researcher_invoke_state(query, runtime),
                config={"callbacks": callbacks} if callbacks else None,
            )
        except Exception as exc:  # noqa: BLE001 - captured as per-item failure
            raise RuntimeError(f"researcher worker failed for query {query.query!r}: {exc}") from exc

        try:
            structured = result.get("structured_response") if isinstance(result, dict) else None
            if structured is None:
                raise ValueError("researcher worker did not return structured ResearchNotes")
            note = ResearchNotes.model_validate(structured)
        except Exception as exc:  # noqa: BLE001 - captured as per-item failure
            raise ValueError(
                f"researcher worker returned invalid ResearchNotes for query {query.query!r}: {exc}"
            ) from exc

        return note


def _research_note_slug(text: str) -> str:
    """Return a compact filesystem-safe slug for a research note."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    slug = slug[:_NOTE_SLUG_MAX_LENGTH].strip("_")
    return slug or "research_note"


def _research_note_path(query: ResearchQuery, note: ResearchNotes, index: int) -> str:
    """Build a stable /shared path for a returned research note."""
    digest_input = json.dumps(query.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()[:8]
    slug = _research_note_slug(note.query_topic or query.query)
    return f"/shared/research_note_{index:02d}_{slug}_{digest}.json"


def _research_note_files(queries: list[ResearchQuery], notes: list[ResearchNotes]) -> list[tuple[str, bytes]]:
    """Serialize returned research notes as shared JSON files."""
    return [
        (
            _research_note_path(query, note, index),
            json.dumps(note.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False).encode("utf-8"),
        )
        for index, (query, note) in enumerate(zip(queries, notes, strict=False), start=1)
    ]


def _persist_research_notes(
    *,
    backend: Any | None,
    queries: list[ResearchQuery],
    notes: list[ResearchNotes],
) -> None:
    """Persist returned ResearchNotes into parent /shared state."""
    if backend is None or not notes:
        return

    responses = backend.upload_files(_research_note_files(queries, notes))
    errors = [f"{response.path}: {response.error}" for response in responses if getattr(response, "error", None)]
    if errors:
        raise RuntimeError(f"failed to persist research note file(s): {'; '.join(errors)}")


async def _run_research_queries(
    *,
    queries: list[ResearchQuery],
    researcher_runnable: Any,
    runtime: ToolRuntime | None,
    callbacks: list[Any],
    max_concurrency: int,
) -> tuple[list[ResearchQuery], list[ResearchNotes], list[str]]:
    """Run researcher workers concurrently and collect successful query/note pairs plus surfaced errors."""
    semaphore = asyncio.Semaphore(min(max_concurrency, len(queries)))
    raw_results = await asyncio.gather(
        *(
            _run_research_query(
                query=query,
                researcher_runnable=researcher_runnable,
                runtime=runtime,
                callbacks=callbacks,
                semaphore=semaphore,
            )
            for query in queries
        ),
        return_exceptions=True,
    )

    successful_queries: list[ResearchQuery] = []
    notes: list[ResearchNotes] = []
    errors: list[str] = []
    for query, raw_result in zip(queries, raw_results, strict=False):
        if isinstance(raw_result, BaseException):
            error = str(raw_result) or raw_result.__class__.__name__
            errors.append(f"{query.query}: {error}")
        else:
            successful_queries.append(query)
            notes.append(raw_result)
    return successful_queries, notes, errors


def build_research_batch_tool(
    *,
    researcher_runnable: Any,
    callbacks: list[Any],
    max_research_concurrency: int,
    backend: Any | None = None,
    source_registry_middleware: Any | None = None,
) -> BaseTool:
    """Build an orchestrator-only tool that runs researcher tasks concurrently."""

    @tool
    async def run_research_batch(
        queries: list[ResearchQuery],
        runtime: ToolRuntime = _NO_TOOL_RUNTIME,
    ) -> str:
        """Run planned research queries in parallel and return ResearchNotes JSON."""
        if not queries:
            return "[]"

        if len(queries) > max_research_concurrency:
            raise ValueError(
                f"run_research_batch accepts at most {max_research_concurrency} curated queries. "
                f"Received {len(queries)}. Rank, merge, or drop lower-priority queries and call again."
            )
        successful_queries, notes, errors = await _run_research_queries(
            queries=queries,
            researcher_runnable=researcher_runnable,
            runtime=runtime,
            callbacks=callbacks,
            max_concurrency=max_research_concurrency,
        )
        if source_registry_middleware is not None:
            source_registry_middleware.register_research_note_sources(notes)
        _persist_research_notes(backend=backend, queries=successful_queries, notes=notes)

        if errors:
            retained_detail = ""
            if notes:
                retained_actions = []
                if source_registry_middleware is not None:
                    retained_actions.append("registered")
                if backend is not None:
                    retained_actions.append("persisted under /shared/")
                retained_text = " and ".join(retained_actions) if retained_actions else "retained"
                retained_detail = (
                    f" {len(notes)} successful researcher worker(s) were {retained_text}; "
                    "resubmit only the failed queries."
                )
            raise RuntimeError(
                f"run_research_batch failed for {len(errors)} of {len(queries)} researcher worker(s). "
                f"Errors: {'; '.join(errors)}.{retained_detail}"
            )

        return json.dumps(
            [note.model_dump(mode="json", exclude_none=True) for note in notes],
            indent=2,
            ensure_ascii=False,
        )

    return run_research_batch
