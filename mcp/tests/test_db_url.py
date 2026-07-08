# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Database URL normalization tests."""

import pytest

from aiq_mcp.db_url import normalize_postgres_url


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
