# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Typed models for the public NeMo Retriever REST wire contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator


class _WireModel(BaseModel):
    """Forward-compatible base for versioned service responses."""

    model_config = ConfigDict(extra="allow")


class CollectionWire(_WireModel):
    name: str
    scope: str
    status: str = "active"
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class CollectionPageWire(_WireModel):
    items: list[CollectionWire] = Field(default_factory=list)
    next_token: str | None = None


class CollectionDeleteWire(_WireModel):
    name: str
    scope: str
    existed: bool
    deleted: bool
    status: str
    cleanup_pending: bool = False


class DocumentWire(_WireModel):
    document_id: str
    collection_name: str
    scope: str
    filename: str
    content_sha256: str
    document_version: str
    status: str
    chunk_count: int = 0
    job_id: str | None = None
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class DocumentPageWire(_WireModel):
    items: list[DocumentWire] = Field(default_factory=list)
    next_token: str | None = None


class DocumentDeleteWire(_WireModel):
    document_id: str
    collection_name: str
    scope: str
    existed: bool
    deleted: bool
    status: str
    cleanup_pending: bool = False


class JobCreatedWire(_WireModel):
    job_id: str
    expected_documents: int
    status: str
    created_at: datetime
    label: str | None = None
    trace_id: str | None = None
    collection_name: str | None = None
    operation: str = "append"


class JobAggregateWire(_WireModel):
    job_id: str
    expected_documents: int
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finalized_at: datetime | None = None
    elapsed_s: float | None = None
    label: str | None = None
    trace_id: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    document_ids: list[str] = Field(default_factory=list)
    collection_name: str | None = None
    operation: str = "append"


class UploadAcceptedWire(_WireModel):
    document_id: str
    attempt_id: str
    job_id: str | None = None
    content_sha256: str
    status: str
    created_at: datetime


class JobDocumentWire(_WireModel):
    document_id: str
    attempt_id: str
    job_id: str
    status: str
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_s: float | None = None
    filename: str | None = None
    result_rows: int | None = None
    error: str | None = None
    collection_name: str | None = None
    content_sha256: str | None = None


class JobDocumentsPageWire(_WireModel):
    job_id: str
    total: int
    total_filtered: int
    offset: int
    limit: int
    items: list[JobDocumentWire] = Field(default_factory=list)


class QueryHitWire(_WireModel):
    chunk_id: str
    document_id: str
    text: str
    distance: float = Field(allow_inf_nan=False)
    filename: str
    page_number: int | None = None
    content_type: str | None = None
    source: Any = None
    source_id: str | None = None
    stored_image_uri: str | None = None
    bbox: Any = None
    bbox_xyxy_norm: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("page_number", mode="before")
    @classmethod
    def _normalize_page(cls, value: Any) -> int | None:
        if value in (None, "", -1, 0):
            return None
        return max(1, int(value))


class QueryResultWire(_WireModel):
    hits: list[QueryHitWire] = Field(default_factory=list)


class QueryResponseWire(_WireModel):
    results: list[QueryResultWire]
