# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.  # noqa: E501
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

"""State models for deep research agent."""

from typing import Annotated
from typing import Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from pydantic import Field

from aiq_agent.knowledge import AvailableDocument

UNVERIFIED_CITATION_STATUS = "unverified"
NO_TOOLS_AVAILABLE_REASON = "no_tools_available"
SOURCES_NOT_CAPTURED_REASON = "sources_not_captured"

_UNVERIFIED_CITATION_WARNINGS = {
    NO_TOOLS_AVAILABLE_REASON: (
        "Warning: This report could not be citation-verified because no research tools were available. "
        "Review the findings before relying on them."
    ),
    SOURCES_NOT_CAPTURED_REASON: (
        "Warning: This report could not be citation-verified because no sources were captured. "
        "Review the findings before relying on them."
    ),
}


def _merge_dict_state(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    if not left:
        return right or {}
    if not right:
        return left
    merged = dict(left)
    merged.update(right)
    return merged


def citation_verification_warning(reason: str | None) -> str:
    """Return a user-facing warning for an unverified citation disposition."""
    return _UNVERIFIED_CITATION_WARNINGS.get(
        reason or "",
        "Warning: This report could not be citation-verified. Review the findings before relying on them.",
    )


def public_citation_verification_status(status: Any) -> dict[str, str] | None:
    """Convert internal citation-verification diagnostics into a safe public disposition."""
    if not isinstance(status, dict) or status.get("status") != UNVERIFIED_CITATION_STATUS:
        return None

    raw_reason = status.get("reason")
    reason = raw_reason if isinstance(raw_reason, str) and raw_reason else "unknown"
    return {
        "status": UNVERIFIED_CITATION_STATUS,
        "reason": reason,
        "warning": citation_verification_warning(reason),
    }


def prepend_citation_verification_warning(content: str, status: Any) -> str:
    """Prefix report content with the public unverified warning, once."""
    public_status = public_citation_verification_status(status)
    if public_status is None:
        return content

    warning = public_status["warning"]
    if content.startswith(warning):
        return content
    return f"{warning}\n\n{content}"


def strip_citation_verification_warning(content: str, status: Any) -> str:
    """Remove a public unverified warning prefix from report content."""
    public_status = public_citation_verification_status(status)
    if public_status is None:
        return content

    warning = public_status["warning"]
    if not content.startswith(warning):
        return content
    return content.removeprefix(warning).lstrip("\n")


class DeepResearchAgentState(BaseModel):
    """
    State for deep research agent.

    The deepagents-based DeepResearcherAgent manages its own internal state
    through the deepagents library. This state primarily handles the interface
    with the orchestrator.

    Attributes:
        messages: Conversation history with LangGraph message reducer.
        data_sources: List of data sources selected by the user.
        user_info: Optional user information.
        tools_info: Information about available tools.
        todos: Todo list managed by TodoListMiddleware.
        files: Virtual filesystem managed by FilesystemMiddleware.
        subagents: Status of configured DeepAgents subagents.
        rubric: DeepAgents rubric used by RubricMiddleware when available.
        clarifier_result: Log from clarifier agent dialog.
        available_documents: User-uploaded documents with summaries for context.
        citation_verification_status: Set when citation verification was skipped
            because the source registry was empty. ``None`` means the report was
            verified normally. When populated, contains keys: ``status``
            (``"unverified"``), ``reason``, ``available_tool_count``,
            ``unavailable_tools``. Downstream consumers can read this to flag
            unverified results.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    data_sources: list[str] | None = None
    user_info: dict[str, Any] | None = None
    tools_info: list[dict[str, Any]] | None = None
    todos: list[dict[str, Any]] = Field(default_factory=list)
    files: Annotated[dict[str, Any], _merge_dict_state] = Field(default_factory=dict)
    subagents: list[dict[str, Any]] = Field(default_factory=list)
    rubric: str | None = None
    clarifier_result: str | None = None
    available_documents: list[AvailableDocument] | None = None
    citation_verification_status: dict[str, Any] | None = None
