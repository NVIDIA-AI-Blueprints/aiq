# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Database URL helpers for the AI-Q MCP runtime."""

from __future__ import annotations

import re


def normalize_postgres_url(value: str, *, label: str) -> str:
    """Return a Postgres URL normalized for drivers that expect bare schemes."""
    normalized = value.strip()
    normalized = re.sub(r"^postgresql\+[^:]+://", "postgresql://", normalized)
    normalized = re.sub(r"^postgres\+[^:]+://", "postgres://", normalized)
    if normalized.startswith("sqlite"):
        raise ValueError(f"{label} must be a Postgres DSN; SQLite is not supported alongside the MCP server")
    if not normalized.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"{label} must be a Postgres DSN that starts with postgresql:// or postgres://")
    return normalized
