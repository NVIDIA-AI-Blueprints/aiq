# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared GSF response fixtures."""

import pytest


@pytest.fixture
def catalog_search_api_response() -> dict:
    """Current GSF question-entity-coverage response envelope."""

    return {
        "data": {
            "coverage": 0.5,
            "candidates": [
                {
                    "label": "ColumnAttribute",
                    "attribute": "recognized_revenue",
                    "term": "Revenue",
                    "id": "attr:revenue",
                },
                {
                    "label": "SqlAttribute",
                    "attribute": "net_revenue_sql",
                    "term": "Net Revenue",
                    "id": "sql-attr:net-revenue",
                },
            ],
        }
    }


@pytest.fixture
def catalog_search_response() -> dict:
    """Normalized catalog response used by NAT registration tests."""

    return {
        "request_id": "gsf-catalog-request-1",
        "coverage": 0.5,
        "candidates": [
            {
                "label": "ColumnAttribute",
                "attribute": "recognized_revenue",
                "term": "Revenue",
                "id": "attr:revenue",
            }
        ],
        "truncated": False,
    }


@pytest.fixture
def chat_sql_answer() -> dict:
    """Current GSF chat-completions SQL answer envelope."""

    return {
        "response": "Revenue was returned for two quarters.",
        "thoughts": "- Constructing SQL: Used quarterly_results.",
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
        "thoughts": "- Constructing PQL: Predicted customer churn over 30 days.",
        "sql_code": "PREDICT churn FOR customers NEXT 30 DAYS",
        "sql_columns": [{"name": "customer_id"}, {"name": "score"}],
        "sql_response_from_db": ['[{"customer_id":"customer-1","score":0.9}]'],
        "custom_analyses_used": [],
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
        "thoughts": "- Constructing SQL: Used quarterly_results.",
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
        "thoughts": "- Constructing PQL: Predicted customer churn over 30 days.",
        "pql": "PREDICT churn FOR customers NEXT 30 DAYS",
        "columns": [{"name": "customer_id"}, {"name": "score"}],
        "rows": [{"customer_id": "customer-1", "score": 0.9}],
        "truncated": False,
        "custom_analyses_used": [],
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
