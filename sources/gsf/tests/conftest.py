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
