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


class ResultColumn(GSFResponse):
    """A column in a bounded SQL result."""

    name: str
    data_type: str


class SemanticContext(GSFResponse):
    """Semantic provenance used to produce a SQL query."""

    metrics: list[dict[str, Any]] = Field(default_factory=list)
    grain: str | None = None
    units: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)


class TextToSQLRequest(GSFRequest):
    """Generate validated SQL and optionally execute it with bounded results."""

    question: str = Field(min_length=1, max_length=4_096)
    database_name: str | None = None
    execute: bool = True
    object_ids: list[str] = Field(default_factory=list)
    max_rows: int = Field(default=1_000, ge=1)


class TextToSQLResponse(GSFResponse):
    """Validated SQL, bounded rows, and semantic provenance returned by GSF."""

    request_id: str
    sql: str
    columns: list[ResultColumn]
    rows: list[dict[str, Any]]
    truncated: bool
    objects_used: list[str] = Field(default_factory=list)
    joins_used: list[dict[str, Any]] = Field(default_factory=list)
    semantic_context: SemanticContext
    validation_attempts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timings: dict[str, int] = Field(default_factory=dict)


class QueryContextRequest(GSFRequest):
    """Build compact, authorized context for a later SQL-generation step."""

    question: str = Field(min_length=1, max_length=4_096)
    database_name: str | None = None
    object_ids: list[str] = Field(default_factory=list)
    token_budget: int | None = Field(default=None, ge=1)


class QueryContextResponse(GSFResponse):
    """Token-budgeted semantic and physical metadata relevant to a question."""

    request_id: str
    tables: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    keys: list[dict[str, Any]] = Field(default_factory=list)
    join_paths: list[dict[str, Any]] = Field(default_factory=list)
    values: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    grain: str | None = None
    units: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False
