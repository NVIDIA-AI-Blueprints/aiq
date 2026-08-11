# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Final evidence and citation handling for data-science answers."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import AnyMessage
from langchain_core.messages import ToolMessage

from aiq_agent.common import get_source_id_for_tool
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.citation_verification import SourceEntry
from aiq_agent.common.citation_verification import SourceRegistry
from aiq_agent.common.citation_verification import classify_empty_source_registry_reason
from aiq_agent.common.citation_verification import extract_sources_from_tool_result
from aiq_agent.common.citation_verification import is_non_citable_status_output
from aiq_agent.common.citation_verification import sanitize_report
from aiq_agent.common.citation_verification import verify_citations


def capture_data_sources(
    messages: Sequence[AnyMessage],
    *,
    registry: SourceRegistry,
    eligible_tool_names: frozenset[str],
) -> None:
    """Capture citable output from configured AI-Q data-source tools."""
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name not in eligible_tool_names:
            continue
        source_id = get_source_id_for_tool(message.name)
        if source_id is None:
            continue
        content = str(message.content or "")
        if message.name.startswith("gsf__") and not is_non_citable_status_output(content):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                request_id = payload.get("request_id")
                if isinstance(request_id, str) and request_id.strip():
                    base_key = f"{message.name} request {request_id.strip()}"
                else:
                    base_key = f"{message.name} result"
                citation_key = base_key
                suffix = 2
                while registry.has_citation_key(citation_key):
                    citation_key = f"{base_key} ({suffix})"
                    suffix += 1
                registry.add(
                    SourceEntry(
                        citation_key=citation_key,
                        title=f"GSF {message.name.removeprefix('gsf__').replace('_', ' ')} receipt",
                        source_type=source_id,
                        tool_name=message.name,
                    )
                )
                continue
        for source in extract_sources_from_tool_result(
            message.name,
            content,
            source_id=source_id,
            result_status=getattr(message, "status", None),
        ):
            registry.add(source)


def _append_minimal_citations(report: str, sources: Sequence[SourceEntry]) -> str:
    citable_sources = [source for source in sources if source.url or source.citation_key]
    if not citable_sources:
        return report

    content = re.sub(
        r"\n{1,2}(?:\*\*References:?\*\*|#{2,3}\s+(?:References|Sources))\s*$",
        "",
        report.rstrip(),
        flags=re.IGNORECASE,
    ).rstrip()
    markers = "".join(f"[{index}]" for index in range(1, len(citable_sources) + 1))
    if content.endswith((".", "!", "?")):
        content = f"{content[:-1]} {markers}{content[-1]}"
    else:
        content = f"{content} {markers}"

    references = []
    for index, source in enumerate(citable_sources, start=1):
        if source.url:
            references.append(f"- [{index}] {source.title or source.url} - {source.url}")
        else:
            references.append(f"- [{index}] {source.citation_key}")
    return f"{content}\n\n## Sources\n" + "\n".join(references)


def finalize_data_science_messages(
    messages: Sequence[AnyMessage],
    *,
    registry: SourceRegistry,
    callbacks: Sequence[Any] = (),
    data_sources: list[str] | None = None,
    available_tools: list[Any] | None = None,
) -> list[AnyMessage]:
    """Return one grounded final answer or raise AI-Q's typed no-source error."""
    finalized = list(messages)
    if not finalized or not isinstance(finalized[-1], AIMessage):
        return finalized

    content = str(finalized[-1].content or "")
    sources = registry.all_sources()
    if not sources:
        generated_answer = sanitize_report(content).sanitized_report if content else None
        raise EmptySourceRegistryError(
            "data science",
            available_count=len(available_tools or []),
            reason=classify_empty_source_registry_reason(data_sources, len(available_tools or []), []),
            generated_answer=generated_answer,
        )

    verification = verify_citations(content, registry, reference_sources=sources)
    content = verification.verified_report
    if not verification.valid_citations:
        content = _append_minimal_citations(content, sources)
    content = sanitize_report(content).sanitized_report
    finalized[-1] = finalized[-1].model_copy(update={"content": content})

    for callback in callbacks:
        emit = getattr(callback, "emit_final_report", None)
        if emit is not None:
            emit(content)
            break
    return finalized


__all__ = ["capture_data_sources", "finalize_data_science_messages"]
