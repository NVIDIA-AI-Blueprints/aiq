# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Typed, NAT-independent contracts for GSF capabilities."""

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class GSFRequest(BaseModel):
    """Base model for data sent from AI-Q to GSF."""

    model_config = ConfigDict(extra="forbid")


class GSFResponse(BaseModel):
    """Base model for the validated subset of data returned by GSF."""

    model_config = ConfigDict(extra="ignore")


class CatalogSearchRequest(GSFRequest):
    """Provisional catalog-search input retained for the unavailable placeholder."""

    question: str = Field(min_length=1, max_length=4_096)
    database_name: str | None = None
    max_results: int = Field(default=10, ge=1, le=100)
    token_budget: int | None = Field(default=None, ge=1)


class ChatCompletionsRequest(GSFRequest):
    """Current GSF chat-completions request shared by SQL and prediction flows."""

    question: str = Field(min_length=1, max_length=4_096)
    conversation_id: str | None = None
    prediction: bool | None = None
    target_db: str | None = None


class ChatCompletionResult(GSFResponse):
    """Final structured answer extracted from the GSF SSE event stream."""

    answer: dict[str, Any]
    request_id: str | None = None


class ResultColumn(GSFResponse):
    """A column in a bounded SQL result."""

    name: str
    data_type: str | None = None


class SemanticContext(GSFResponse):
    """Semantic provenance used to produce a SQL query."""

    metrics: list[dict[str, Any]] = Field(default_factory=list)
    grain: str | None = None
    units: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)


class TextToSQLRequest(GSFRequest):
    """Generate and execute validated SQL with bounded results."""

    question: str = Field(min_length=1, max_length=4_096)
    database_name: str | None = None
    max_rows: int = Field(default=1_000, ge=1)


class TextToSQLResponse(GSFResponse):
    """Validated SQL, bounded rows, and semantic provenance returned by GSF."""

    request_id: str | None = None
    response: str | None = None
    sql: str
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    custom_analyses_used: list[Any] | None = None
    objects_used: list[str] | None = None
    joins_used: list[dict[str, Any]] | None = None
    semantic_context: SemanticContext | None = None
    validation_attempts: list[dict[str, Any]] | None = None
    assumptions: list[str] | None = None
    warnings: list[str] | None = None
    timings: dict[str, int | float] | None = None


class QueryContextRequest(GSFRequest):
    """Build compact, authorized context for a later SQL-generation step."""

    question: str = Field(min_length=1, max_length=4_096)
    database_name: str | None = None
    object_ids: list[str] = Field(default_factory=list)
    token_budget: int | None = Field(default=None, ge=1)
