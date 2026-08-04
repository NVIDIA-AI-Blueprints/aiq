# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest
from gsf.models import QueryContextRequest
from gsf.models import QueryContextResponse
from gsf.models import TextToSQLRequest
from gsf.models import TextToSQLResponse
from pydantic import ValidationError


def test_text_to_sql_request_supports_optional_database_name() -> None:
    request = TextToSQLRequest(question="Show quarterly revenue", database_name="benchmark_db")

    assert request.database_name == "benchmark_db"
    assert request.execute is True
    assert request.max_rows == 1_000


def test_query_context_request_omits_optional_database_name() -> None:
    payload = QueryContextRequest(question="What revenue data is available?").model_dump(exclude_none=True)

    assert "database_name" not in payload


def test_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TextToSQLRequest.model_validate({"question": "Show revenue", "unknown": True})


def test_text_to_sql_response_requires_provenance(text_to_sql_response: dict) -> None:
    text_to_sql_response.pop("request_id")

    with pytest.raises(ValidationError):
        TextToSQLResponse.model_validate(text_to_sql_response)


def test_query_context_response_accepts_future_fields(query_context_response: dict) -> None:
    query_context_response["future_gsf_metadata"] = {"enabled": True}

    result = QueryContextResponse.model_validate(query_context_response)

    assert result.request_id == "gsf-request-2"
    assert not hasattr(result, "future_gsf_metadata")
