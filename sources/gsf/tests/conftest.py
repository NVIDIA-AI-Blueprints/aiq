# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest


@pytest.fixture
def chat_sql_answer() -> dict:
    """Current GSF chat-completions SQL answer envelope."""

    return {
        "response": "Revenue was returned for two quarters.",
        "sql_code": "SELECT revenue FROM quarterly_results",
        "sql_columns": [],
        "custom_analyses_used": [],
        "sql_response_from_db": ['[{"revenue":100},{"revenue":200}]'],
    }


@pytest.fixture
def chat_pql_answer() -> dict:
    """Current GSF chat-completions PQL answer envelope."""

    return {
        "response": "A churn prediction query was generated.",
        "sql_code": "PREDICT churn FOR customers NEXT 30 DAYS",
        "objects_used": ["prediction:churn"],
        "semantic_context": {
            "metrics": [{"id": "prediction:churn"}],
            "grain": "customer",
            "units": [],
            "filters": [],
            "rules": [],
            "omissions": [],
        },
        "warnings": [],
        "timings": {"total_ms": 20},
    }


@pytest.fixture
def text_to_sql_response() -> dict:
    """Normalized response used by the NAT registration tests."""

    return {
        "request_id": "gsf-request-1",
        "response": "Revenue was returned for two quarters.",
        "sql": "SELECT revenue FROM quarterly_results",
        "columns": [{"name": "revenue", "data_type": "numeric"}],
        "rows": [{"revenue": 100}, {"revenue": 200}],
        "truncated": False,
        "objects_used": ["metric:revenue"],
        "joins_used": [],
        "semantic_context": {
            "metrics": [{"id": "metric:revenue"}],
            "grain": "quarter",
            "units": ["USD"],
            "filters": [],
            "rules": [],
            "omissions": [],
        },
        "validation_attempts": [],
        "warnings": [],
        "timings": {"total_ms": 25},
    }


@pytest.fixture
def text_to_pql_response() -> dict:
    """Normalized PQL response used by the NAT registration tests."""

    return {
        "request_id": "gsf-request-2",
        "response": "A churn prediction query was generated.",
        "pql": "PREDICT churn FOR customers NEXT 30 DAYS",
        "objects_used": ["prediction:churn"],
        "semantic_context": {
            "metrics": [{"id": "prediction:churn"}],
            "grain": "customer",
            "units": [],
            "filters": [],
            "rules": [],
            "omissions": [],
        },
        "warnings": [],
        "timings": {"total_ms": 20},
    }
