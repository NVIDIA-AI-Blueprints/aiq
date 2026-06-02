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

"""Structured response contracts for deep researcher planning, research, and synthesis."""

from typing import ClassVar
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class _StrictContract(BaseModel):
    """Base model for structured response schemas."""

    model_config: ClassVar[ConfigDict] = {"extra": "forbid"}


class TaskAnalysis(_StrictContract):
    """Planner analysis of the user's research request."""

    user_intent: str = Field(description="Brief statement of what the user wants to achieve.")
    explicit_requirements: list[str] = Field(description="Requirements explicitly stated by the user.")
    implicit_requirements: list[str] = Field(description="Requirements implied by the request.")
    out_of_scope: list[str] = Field(description="Tangential topics that should be excluded from the report.")
    language: str = Field(description="Language to use for the plan, notes, and final report.")


class AnswerOption(_StrictContract):
    """A user-provided option or output choice the final answer may need to select."""

    id: str = Field(description="Stable option identifier, such as 'A' or 'price_above_100'.")
    label: str = Field(description="User-facing option text.")
    description: str = Field(default="", description="Additional option context, if available.")


class AnswerComponent(_StrictContract):
    """Required evidence or synthesis component for the final answer."""

    id: str = Field(description="Stable component identifier, such as 'latest_price_anchor'.")
    name: str = Field(description="Short human-readable component name.")
    description: str = Field(description="What the writer must cover for this component.")


class AnswerStrategy(_StrictContract):
    """Planner guidance for the final answer shape and synthesis logic."""

    answer_type: Literal[
        "long_form_report",
        "brief_answer",
        "table",
        "comparison",
        "prediction",
        "multiple_choice",
        "data_extraction",
        "custom",
    ] = Field(description="The intended final output shape.")
    title: str = Field(description="Concise human-facing title for the final output.")
    response_shape: str = Field(description="Concrete description of the expected final Markdown shape.")
    selection_mode: Literal["none", "single_choice", "top_k", "multi_select", "threshold", "free_text"] = Field(
        description="Decision rule for final answer selection, if any."
    )
    expected_count: int | None = Field(
        default=None,
        description="Expected number of selected answers for single_choice/top_k/multi_select, when applicable.",
    )
    options: list[AnswerOption] = Field(
        default_factory=list,
        description="Candidate options when the user request includes choices or buckets.",
    )
    required_components: list[AnswerComponent] = Field(
        description="Evidence and synthesis components that must be covered in the final answer."
    )
    assembly_instruction: str = Field(description="Specific writer-facing instruction for assembling the final answer.")


class Constraint(_StrictContract):
    """Acceptance criterion that the final answer should satisfy."""

    category: Literal["content", "source", "structure", "depth", "format", "exclusion"] = Field(
        description="Constraint category."
    )
    constraint: str = Field(description="Specific, actionable constraint text.")
    rationale: str = Field(description="Why this constraint exists.")
    verification: str = Field(description="How to check whether the final report satisfies this constraint.")


class ResearchQuery(_StrictContract):
    """Self-contained research query for a researcher worker."""

    query: str = Field(description="Specific, self-contained search or document query.")
    subqueries: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered concrete search angles the researcher must cover after the main query. "
            "Use 2-5 subqueries for broad, survey, overview, landscape, taxonomy, trend, "
            "application, challenge, risk, benefit, or multi-component queries."
        ),
    )
    tool: str = Field(description="Exact available source tool name to use; not a category label.")
    target_components: list[str] = Field(description="Answer components this query is intended to support.")
    rationale: str = Field(description="Why this query is needed.")


class ResearchPlan(_StrictContract):
    """Structured plan produced by the planner subagent."""

    task_analysis: TaskAnalysis = Field(description="Planner analysis of the user's request.")
    answer_strategy: AnswerStrategy = Field(description="Final answer shape and synthesis strategy.")
    constraints: list[Constraint] = Field(description="Acceptance criteria for the final answer.")
    queries: list[ResearchQuery] = Field(description="Queries for researcher workers to execute.")


class ResearchSource(_StrictContract):
    """Source used by a researcher worker."""

    id: int = Field(description="Integer source identifier used by findings in this note.")
    title: str = Field(description="Source title or document name.")
    source_type: Literal["url", "internal_document", "tool"] = Field(
        description="Kind of source referenced by locator."
    )
    locator: str = Field(
        description=(
            "URL for web sources, document/page citation for internal documents, "
            "or raw tool name for URL-less structured tool results."
        )
    )


class ResearchFinding(_StrictContract):
    """Atomic finding captured from one or more sources."""

    claim: str = Field(description="Concise factual claim or analytical conclusion.")
    evidence: str = Field(description="Detailed supporting evidence, including dates, figures, names, and context.")
    source_ids: list[int] = Field(description="IDs from the sources list that support this finding.")
    confidence: Literal["low", "medium", "high"] = Field(description="Confidence in the finding.")
    caveats: list[str] = Field(description="Limitations, disagreements, or context needed to use this finding.")


class ResearchGap(_StrictContract):
    """Information gap identified during research."""

    description: str = Field(description="Missing or weakly supported information.")
    impact: str = Field(description="Why the gap matters for the final report.")
    suggested_follow_up_queries: list[str] = Field(description="Queries that could close the gap.")


class ResearchNotes(_StrictContract):
    """Structured notes produced by a researcher worker."""

    query_topic: str = Field(description="Short topic label for this research note.")
    target_components: list[str] = Field(description="Answer components these notes support.")
    summary: str = Field(description="Brief synthesis of the research results.")
    findings: list[ResearchFinding] = Field(description="Detailed findings supported by cited sources.")
    gaps: list[ResearchGap] = Field(description="Open gaps or weak spots discovered during research.")
    sources: list[ResearchSource] = Field(description="Every source used by these notes.")
    narrative_notes: str = Field(description="Detailed synthesis preserving nuance for final answer writing.")
    language: str = Field(description="Language used in these research notes.")


class WriterOutput(_StrictContract):
    """Structured output produced by the writer subagent."""

    answer_markdown: str = Field(description="Final user-facing Markdown answer with normal source citations.")
    answer_type: Literal[
        "long_form_report",
        "brief_answer",
        "table",
        "comparison",
        "prediction",
        "multiple_choice",
        "data_extraction",
        "custom",
    ] = Field(description="The final output shape used.")
    citations_used: list[int] = Field(description="Citation numbers referenced in answer_markdown.")
    gaps: list[str] = Field(default_factory=list, description="Material gaps or limitations carried into the answer.")
    confidence: Literal["low", "medium", "high"] = Field(description="Overall confidence in the final answer.")


class ResearchBatchItemResult(_StrictContract):
    """Result for one researcher worker in a batched research call."""

    query: ResearchQuery = Field(description="ResearchQuery assigned to this worker.")
    status: Literal["succeeded", "failed", "timed_out", "rejected"] = Field(
        description="Outcome for this individual researcher worker."
    )
    file_path: str | None = Field(default=None, description="Persisted /shared path for successful notes.")
    note: ResearchNotes | None = Field(
        default=None,
        description="Structured notes returned by the researcher before persistence; compact summaries omit this.",
    )
    error: str | None = Field(default=None, description="Error text for failed, timed out, or rejected items.")
    elapsed_seconds: float = Field(description="Elapsed wall-clock seconds for this item.")


class ResearchBatchResult(_StrictContract):
    """Structured result returned by run_research_batch."""

    status: Literal["succeeded", "partial", "failed", "rejected"] = Field(description="Overall batch outcome.")
    total: int = Field(description="Total number of input queries.")
    succeeded: int = Field(description="Number of successful researcher workers.")
    failed: int = Field(description="Number of failed researcher workers.")
    timed_out: int = Field(description="Number of timed-out researcher workers.")
    files: list[str] = Field(description="Persisted /shared paths for successful notes.")
    results: list[ResearchBatchItemResult] = Field(description="Per-query batch results.")
    error: str | None = Field(default=None, description="Batch-level error, if any.")
