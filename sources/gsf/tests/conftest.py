# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest


@pytest.fixture
def text_to_sql_response() -> dict:
    return {
        "request_id": "gsf-request-1",
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
def query_context_response() -> dict:
    return {
        "request_id": "gsf-request-2",
        "tables": [{"id": "table:quarterly_results", "grain": "quarter"}],
        "columns": [{"table_id": "table:quarterly_results", "name": "revenue", "data_type": "numeric"}],
        "keys": [{"table_id": "table:quarterly_results", "columns": ["quarter"]}],
        "join_paths": [],
        "values": [],
        "metrics": [{"id": "metric:revenue", "unit": "USD"}],
        "grain": "quarter",
        "units": ["USD"],
        "rules": [],
        "omissions": [],
        "warnings": [],
        "truncated": False,
    }
