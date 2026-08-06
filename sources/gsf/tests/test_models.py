# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest
from gsf.models import CatalogCandidate
from gsf.models import CatalogSearchRequest
from gsf.models import CatalogSearchResponse
from gsf.models import QueryContextRequest
from gsf.models import TextToPQLRequest
from gsf.models import TextToPQLResponse
from gsf.models import TextToSQLRequest
from gsf.models import TextToSQLResponse
from pydantic import ValidationError


def test_catalog_search_request_supports_optional_scope_and_search_controls() -> None:
    request = CatalogSearchRequest(
        question="Find revenue metrics",
        database_name="benchmark_db",
        max_results=20,
        max_distance=0.5,
    )

    assert request.database_name == "benchmark_db"
    assert request.max_results == 20
    assert request.max_distance == 0.5


def test_catalog_search_response_validates_coverage() -> None:
    with pytest.raises(ValidationError):
        CatalogSearchResponse(
            coverage=1.5,
            candidates=[
                CatalogCandidate(
                    label="ColumnAttribute",
                    attribute="revenue",
                    term="Revenue",
                    id="attr:revenue",
                )
            ],
        )


def test_catalog_search_response_ignores_future_fields(catalog_search_response: dict) -> None:
    catalog_search_response["future_gsf_metadata"] = {"enabled": True}

    result = CatalogSearchResponse.model_validate(catalog_search_response)

    assert result.request_id == "gsf-catalog-request-1"
    assert not hasattr(result, "future_gsf_metadata")


def test_text_to_sql_request_supports_optional_database_name() -> None:
    request = TextToSQLRequest(question="Show quarterly revenue", database_name="benchmark_db")

    assert request.database_name == "benchmark_db"
    assert request.max_rows == 1_000


def test_text_to_pql_request_supports_optional_database_name() -> None:
    request = TextToPQLRequest(question="Predict churn", database_name="benchmark_db")

    assert request.database_name == "benchmark_db"


def test_query_context_request_omits_optional_database_name() -> None:
    payload = QueryContextRequest(question="What revenue data is available?").model_dump(exclude_none=True)

    assert "database_name" not in payload


def test_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TextToSQLRequest.model_validate({"question": "Show revenue", "unknown": True})


def test_text_to_sql_response_accepts_missing_future_enrichments() -> None:
    result = TextToSQLResponse.model_validate(
        {
            "sql": "SELECT revenue FROM quarterly_results",
            "rows": [{"revenue": 100}],
        }
    )

    assert result.request_id is None
    assert result.semantic_context is None
    assert result.warnings is None


def test_text_to_pql_response_accepts_missing_future_enrichments() -> None:
    result = TextToPQLResponse.model_validate({"pql": "PREDICT churn FOR customers NEXT 30 DAYS"})

    assert result.request_id is None
    assert result.semantic_context is None
    assert result.warnings is None


def test_text_to_sql_response_ignores_future_fields(text_to_sql_response: dict) -> None:
    text_to_sql_response["future_gsf_metadata"] = {"enabled": True}

    result = TextToSQLResponse.model_validate(text_to_sql_response)

    assert result.request_id == "gsf-request-1"
    assert not hasattr(result, "future_gsf_metadata")
