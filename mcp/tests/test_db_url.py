# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Database URL normalization tests."""

import pytest

from aiq_mcp.db_url import normalize_postgres_url
from aiq_mcp.db_url import require_test_database_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("postgresql://db.example/aiq", "postgresql://db.example/aiq"),
        ("postgres://db.example/aiq", "postgres://db.example/aiq"),
        ("postgresql+asyncpg://db.example/aiq", "postgresql://db.example/aiq"),
        ("postgresql+psycopg://db.example/aiq", "postgresql://db.example/aiq"),
        ("  postgres+asyncpg://db.example/aiq  ", "postgres://db.example/aiq"),
    ],
)
def test_normalize_postgres_url(value: str, expected: str) -> None:
    assert normalize_postgres_url(value, label="test URL") == expected


@pytest.mark.parametrize("value", ["sqlite:///tmp/checkpoints.db", "https://db.example/aiq", "db.example/aiq", ""])
def test_normalize_postgres_url_rejects_non_postgres_values(value: str) -> None:
    with pytest.raises(ValueError, match="must be a Postgres DSN"):
        normalize_postgres_url(value, label="test URL")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("postgresql://db.example/aiq_mcp_test", "postgresql://db.example/aiq_mcp_test"),
        ("postgresql+asyncpg://db.example/AIQ_MCP_TEST", "postgresql://db.example/AIQ_MCP_TEST"),
        ("postgresql://db.example/aiq_mcp_tests", "postgresql://db.example/aiq_mcp_tests"),
        ("postgresql+asyncpg://db.example/AIQ_MCP_TESTS", "postgresql://db.example/AIQ_MCP_TESTS"),
    ],
)
def test_require_test_database_url_accepts_test_database_names(value: str, expected: str) -> None:
    assert require_test_database_url(value, label="test URL") == expected


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://db.example/aiq_mcp",
        "postgresql://db.example/postgres",
        "postgresql://db.example/aiq_mcp_testing",
        "postgresql://db.example/aiq%2Fmcp_test",
        "postgresql://db.example/aiq_mcp_test2",
        "postgresql://db.example/",
        "postgresql://db.example/aiq_mcp_test/extra",
    ],
)
def test_require_test_database_url_refuses_non_test_database_names(value: str) -> None:
    with pytest.raises(ValueError, match="must target a test database whose name ends with _test or _tests"):
        require_test_database_url(value, label="test URL")
