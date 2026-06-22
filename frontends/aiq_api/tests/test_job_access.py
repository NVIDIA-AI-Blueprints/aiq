# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
from datetime import UTC
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from aiq_agent.auth import Principal
from aiq_api.jobs import access as job_access
from aiq_api.jobs.access import authorize_job_access
from aiq_api.jobs.access import cleanup_job_access
from aiq_api.jobs.access import create_job_access
from aiq_api.jobs.access import ensure_job_access_table
from aiq_api.jobs.access import get_job_access
from aiq_api.jobs.event_store import EventStore


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path / 'test_job_access.db'}"


@pytest.fixture(autouse=True)
def clear_event_store_caches():
    EventStore._tables_initialized.clear()
    job_access._job_access_schema_initialized.clear()
    yield
    EventStore._tables_initialized.clear()
    job_access._job_access_schema_initialized.clear()


def _insert_job_info(db_url: str, job_id: str, *, is_expired: bool = False) -> None:
    from sqlalchemy import text

    engine = EventStore._get_or_create_sync_engine(db_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS job_info ("
                "  job_id TEXT PRIMARY KEY,"
                "  status TEXT,"
                "  config_file TEXT,"
                "  error TEXT,"
                "  output_path TEXT,"
                "  created_at DATETIME,"
                "  updated_at DATETIME,"
                "  expiry_seconds INTEGER,"
                "  output TEXT,"
                "  is_expired BOOLEAN DEFAULT 0"
                ")"
            )
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        conn.execute(
            text(
                "INSERT OR REPLACE INTO job_info "
                "(job_id, status, created_at, updated_at, expiry_seconds, is_expired) "
                "VALUES (:job_id, 'running', :ts, :ts, 3600, :is_expired)"
            ),
            {"job_id": job_id, "ts": now, "is_expired": is_expired},
        )
        conn.commit()


class TestJobAccessStorage:
    def test_create_and_get_job_access(self, db_url):
        principal = Principal(type="jwt", sub="user-1", email="alice@example.com")

        create_job_access("job-1", principal, db_url)

        access = get_job_access("job-1", db_url)
        assert access is not None
        assert access["owner_auth_type"] == "jwt"
        assert access["owner_subject"] == "user-1"
        assert access["owner_email"] == "alice@example.com"

    def test_cleanup_removes_expired_and_orphaned_access_rows(self, db_url):
        ensure_job_access_table(db_url)
        principal = Principal(type="jwt", sub="user-1")
        create_job_access("live-job", principal, db_url)
        create_job_access("expired-job", principal, db_url)
        create_job_access("orphan-job", principal, db_url)

        _insert_job_info(db_url, "live-job", is_expired=False)
        _insert_job_info(db_url, "expired-job", is_expired=True)

        deleted = cleanup_job_access(db_url)

        assert deleted == 2
        assert get_job_access("live-job", db_url) is not None
        assert get_job_access("expired-job", db_url) is None
        assert get_job_access("orphan-job", db_url) is None


class TestAuthorizeJobAccess:
    @pytest.fixture(autouse=True)
    def _enforce_auth(self, monkeypatch):
        # authorize_job_access only consults the ownership table when REQUIRE_AUTH=true.
        # Pin it on so these tests deterministically exercise the enforced path instead
        # of silently passing/failing based on the ambient environment.
        monkeypatch.setenv("REQUIRE_AUTH", "true")

    def test_no_auth_mode_allows_any_caller(self, db_url, monkeypatch):
        """With auth disabled, ownership is intentionally not enforced (documented posture)."""
        monkeypatch.setenv("REQUIRE_AUTH", "false")
        _insert_job_info(db_url, "job-1")
        # No job_access row and a different principal -> still allowed under no-auth.
        job = SimpleNamespace(job_id="job-1", status="running", created_at=None, error=None)
        job_store = SimpleNamespace(get_job=AsyncMock(return_value=job))

        result = asyncio.run(authorize_job_access(job_store, db_url, "job-1", Principal(type="anonymous", sub="anon")))

        assert result is job

    def test_owner_can_access_job(self, db_url):
        _insert_job_info(db_url, "job-1")
        principal = Principal(type="jwt", sub="user-1")
        create_job_access("job-1", principal, db_url)
        job = SimpleNamespace(job_id="job-1", status="running", created_at=None, error=None)
        job_store = SimpleNamespace(get_job=AsyncMock(return_value=job))

        result = asyncio.run(authorize_job_access(job_store, db_url, "job-1", principal))

        assert result is job

    def test_cross_user_access_denied_with_404(self, db_url):
        _insert_job_info(db_url, "job-1")
        create_job_access("job-1", Principal(type="jwt", sub="user-1"), db_url)
        job = SimpleNamespace(job_id="job-1", status="running", created_at=None, error=None)
        job_store = SimpleNamespace(get_job=AsyncMock(return_value=job))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(authorize_job_access(job_store, db_url, "job-1", Principal(type="jwt", sub="user-2")))

        assert exc.value.status_code == 404

    def test_missing_access_row_denied_with_404(self, db_url):
        _insert_job_info(db_url, "job-1")
        job = SimpleNamespace(job_id="job-1", status="running", created_at=None, error=None)
        job_store = SimpleNamespace(get_job=AsyncMock(return_value=job))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(authorize_job_access(job_store, db_url, "job-1", Principal(type="jwt", sub="user-1")))

        assert exc.value.status_code == 404

    def test_missing_job_returns_404_before_access_check(self, db_url):
        job_store = SimpleNamespace(get_job=AsyncMock(return_value=None))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(authorize_job_access(job_store, db_url, "job-1", Principal(type="jwt", sub="user-1")))

        assert exc.value.status_code == 404


class TestRequireVerifiedPrincipal:
    """The report follow-up surfaces depend on this resolving correctly per REQUIRE_AUTH."""

    def test_no_auth_synthesizes_a_usable_principal(self, monkeypatch):
        from aiq_api.jobs.access import require_verified_principal

        monkeypatch.setenv("REQUIRE_AUTH", "false")
        principal = require_verified_principal()
        # No 401/403 in no-auth mode; a stable, non-None principal is returned so
        # chat/HTTP report follow-up works for anonymous callers.
        assert principal is not None
        assert principal.sub

    def test_auth_required_without_verified_principal_raises_403(self, monkeypatch):
        from aiq_api.jobs.access import require_verified_principal

        monkeypatch.setenv("REQUIRE_AUTH", "true")
        with pytest.raises(HTTPException) as exc:
            require_verified_principal()
        assert exc.value.status_code == 403
