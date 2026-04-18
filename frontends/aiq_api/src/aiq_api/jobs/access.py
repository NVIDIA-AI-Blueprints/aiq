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

"""AIQ-owned async job access control helpers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from aiq_agent.auth import Principal
from aiq_agent.auth import get_current_principal

logger = logging.getLogger(__name__)

_JOB_ACCESS_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_job_access_owner ON job_access(owner_auth_type, owner_subject)"
_JOB_ACCESS_SELECT_SQL = text(
    "SELECT job_id, owner_auth_type, owner_subject, owner_email, created_at FROM job_access WHERE job_id = :job_id"
)
_JOB_ACCESS_DELETE_SQL = text("DELETE FROM job_access WHERE job_id = :job_id")
_JOB_ACCESS_CLEANUP_SQL = text(
    "DELETE FROM job_access "
    "WHERE job_id NOT IN (SELECT job_id FROM job_info WHERE is_expired = false OR is_expired = 0)"
)
_JOB_INFO_DELETE_SQL = text("DELETE FROM job_info WHERE job_id = :job_id")
_JOB_EVENTS_DELETE_SQL = text("DELETE FROM job_events WHERE job_id = :job_id")


def _is_postgres(db_url: str) -> bool:
    return db_url.startswith("postgres")


def ensure_job_access_table(db_url: str) -> None:
    """Create the AIQ-owned job access table if it does not exist."""
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        conn.commit()


def create_job_access(job_id: str, principal: Principal, db_url: str) -> None:
    """Persist the verified owner for a newly created job."""
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        conn.execute(_job_access_upsert_sql(db_url), _principal_params(job_id, principal))
        conn.commit()


def get_job_access(job_id: str, db_url: str) -> dict[str, Any] | None:
    """Return job access metadata for a job."""
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        row = conn.execute(_JOB_ACCESS_SELECT_SQL, {"job_id": job_id}).mappings().first()
    return dict(row) if row is not None else None


def delete_job_access(job_id: str, db_url: str) -> int:
    """Delete job access metadata for a specific job."""
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        result = conn.execute(_JOB_ACCESS_DELETE_SQL, {"job_id": job_id})
        conn.commit()
        return result.rowcount or 0


def cleanup_job_access(db_url: str, conn: Connection | None = None) -> int:
    """Delete access rows for expired or missing jobs."""
    if conn is not None:
        _ensure_job_access_schema(conn, db_url)
        result = conn.execute(_JOB_ACCESS_CLEANUP_SQL)
        return result.rowcount or 0

    with _job_access_connection(db_url) as owned_conn:
        _ensure_job_access_schema(owned_conn, db_url)
        result = owned_conn.execute(_JOB_ACCESS_CLEANUP_SQL)
        owned_conn.commit()
        return result.rowcount or 0


def rollback_job_submission(job_id: str, db_url: str) -> None:
    """Best-effort rollback when ownership persistence fails after NAT job creation.

    The submit path must not return an ownerless job ID. If job submission creates
    NAT metadata but `job_access` cannot be written, remove the partial job state.
    """
    from .event_store import EventStore

    EventStore._ensure_table_exists(db_url)
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        conn.execute(_JOB_ACCESS_DELETE_SQL, {"job_id": job_id})
        conn.execute(_JOB_EVENTS_DELETE_SQL, {"job_id": job_id})
        conn.execute(_JOB_INFO_DELETE_SQL, {"job_id": job_id})
        conn.commit()


def require_verified_principal() -> Principal:
    """Return the verified request principal or raise a safe auth error."""
    principal = get_current_principal()
    if principal is None:
        raise HTTPException(403, "Verified principal required for async job access")
    return principal


async def authorize_job_access(job_store: Any, db_url: str, job_id: str, principal: Principal) -> Any:
    """Load a job only if the verified principal owns it."""
    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    access = get_job_access(job_id, db_url)
    if access is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    if not _principal_matches_access(principal, access):
        raise HTTPException(404, f"Job not found: {job_id}")

    return job


def _principal_matches_access(principal: Principal, access: Mapping[str, Any]) -> bool:
    return principal.type == access.get("owner_auth_type") and principal.sub == access.get("owner_subject")


def _job_access_connection(db_url: str):
    from .event_store import EventStore

    engine = EventStore._get_or_create_sync_engine(db_url)
    return engine.connect()


def _ensure_job_access_schema(conn: Connection, db_url: str) -> None:
    conn.execute(text(_job_access_table_sql(db_url)))
    conn.execute(text(_JOB_ACCESS_INDEX_SQL))


def _job_access_table_sql(db_url: str) -> str:
    created_at_type = (
        "TIMESTAMP WITH TIME ZONE DEFAULT NOW()" if _is_postgres(db_url) else "DATETIME DEFAULT CURRENT_TIMESTAMP"
    )
    return (
        "CREATE TABLE IF NOT EXISTS job_access ("
        "  job_id VARCHAR PRIMARY KEY,"
        "  owner_auth_type VARCHAR NOT NULL,"
        "  owner_subject VARCHAR NOT NULL,"
        "  owner_email VARCHAR,"
        f"  created_at {created_at_type}"
        ")"
    )


def _job_access_upsert_sql(db_url: str):
    postgres_upsert = (
        "INSERT INTO job_access (job_id, owner_auth_type, owner_subject, owner_email) "
        "VALUES (:job_id, :owner_auth_type, :owner_subject, :owner_email) "
        "ON CONFLICT(job_id) DO UPDATE SET "
        "owner_auth_type = excluded.owner_auth_type, "
        "owner_subject = excluded.owner_subject, "
        "owner_email = excluded.owner_email"
    )
    sqlite_upsert = (
        "INSERT OR REPLACE INTO job_access (job_id, owner_auth_type, owner_subject, owner_email) "
        "VALUES (:job_id, :owner_auth_type, :owner_subject, :owner_email)"
    )
    return text(postgres_upsert if _is_postgres(db_url) else sqlite_upsert)


def _principal_params(job_id: str, principal: Principal) -> dict[str, str | None]:
    return {
        "job_id": job_id,
        "owner_auth_type": principal.type,
        "owner_subject": principal.sub,
        "owner_email": principal.email,
    }
