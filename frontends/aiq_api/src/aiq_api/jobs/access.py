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

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from aiq_agent.auth import Principal
from aiq_agent.auth import get_current_principal

logger = logging.getLogger(__name__)

_job_access_schema_initialized: set[str] = set()

# Statuses that mean a job no longer holds a live sandbox. Anything else (running,
# pending, submitted, etc.) counts as active for the concurrency guard.
_TERMINAL_STATUS_SQL = "('success','failure','failed','interrupted','cancelled','completed','error')"

_JOB_ACCESS_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_job_access_owner ON job_access(owner_auth_type, owner_subject)"
_JOB_ACCESS_CONVERSATION_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_job_access_conversation ON job_access(conversation_id)"
)
_JOB_ACCESS_SELECT_SQL = text(
    "SELECT job_id, owner_auth_type, owner_subject, owner_email, conversation_id, created_at "
    "FROM job_access WHERE job_id = :job_id"
)
# Most recent completed, non-expired report job for a conversation. The owner predicate is
# applied only when REQUIRE_AUTH=true, mirroring authorize_job_access (which skips ownership
# under REQUIRE_AUTH=false). This keeps the fallback consistent with the auth gate and avoids
# brittle owner-subject matching for the synthesized no-auth principal.
# Agent types whose successful output is a full report eligible for follow-up. Excludes
# non-report agents (e.g. shallow_researcher); legacy rows with NULL agent_type are allowed.
_REPORT_PRODUCING_AGENTS = ("deep_researcher", "report_rewriter")
_REPORT_AGENT_FILTER = (
    "AND (ja.agent_type IS NULL OR ja.agent_type IN (" + ", ".join(f"'{a}'" for a in _REPORT_PRODUCING_AGENTS) + ")) "
)
_LATEST_REPORT_JOB_BASE = (
    "SELECT ja.job_id FROM job_access ja "
    "JOIN job_info ji ON ja.job_id = ji.job_id "
    "WHERE ja.conversation_id = :conversation_id "
    "AND ji.status = 'success' "
    "AND ji.is_expired IS NOT TRUE " + _REPORT_AGENT_FILTER
)
_LATEST_REPORT_JOB_SQL_ANY = text(_LATEST_REPORT_JOB_BASE + "ORDER BY ji.created_at DESC LIMIT 1")
_LATEST_REPORT_JOB_SQL_OWNED = text(
    _LATEST_REPORT_JOB_BASE
    + "AND ja.owner_auth_type = :owner_auth_type AND ja.owner_subject = :owner_subject "
    + "ORDER BY ji.created_at DESC LIMIT 1"
)
_JOB_ACCESS_DELETE_SQL = text("DELETE FROM job_access WHERE job_id = :job_id")
_JOB_ACCESS_CLEANUP_SQL = text(
    "DELETE FROM job_access WHERE job_id NOT IN (SELECT job_id FROM job_info WHERE is_expired IS NOT TRUE)"
)
_JOB_INFO_DELETE_SQL = text("DELETE FROM job_info WHERE job_id = :job_id")
_JOB_EVENTS_DELETE_SQL = text("DELETE FROM job_events WHERE job_id = :job_id")


def _is_postgres(db_url: str) -> bool:
    """Return whether the database URL targets PostgreSQL."""
    return db_url.startswith("postgres")


def ensure_job_access_table(db_url: str) -> None:
    """Create the AIQ-owned job access table if it does not exist."""
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        conn.commit()


def create_job_access(
    job_id: str,
    principal: Principal,
    db_url: str,
    conversation_id: str | None = None,
    agent_type: str | None = None,
) -> None:
    """Persist the verified owner (and originating conversation + agent type) for a new job."""
    with _job_access_connection(db_url) as conn:
        _ensure_job_access_schema(conn, db_url)
        conn.execute(_job_access_upsert_sql(db_url), _principal_params(job_id, principal, conversation_id, agent_type))
        conn.commit()


def get_latest_report_job_for_conversation(
    conversation_id: str | None, principal: Principal, db_url: str
) -> str | None:
    """Return the most recent completed report job submitted in this conversation by this caller.

    Used as the server-side default for report follow-up when the client does not supply an
    explicit ``active_report_job_id``. Returns None (degrade to fresh research) for an empty
    conversation id, no match, or any storage error — it must never raise into the request path.
    """
    if not conversation_id:
        return None
    enforce_owner = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"
    if enforce_owner and principal is None:
        return None
    params: dict[str, str] = {"conversation_id": conversation_id}
    if enforce_owner:
        sql = _LATEST_REPORT_JOB_SQL_OWNED
        params["owner_auth_type"] = principal.type
        params["owner_subject"] = principal.sub
    else:
        sql = _LATEST_REPORT_JOB_SQL_ANY
    try:
        with _job_access_connection(db_url) as conn:
            _ensure_job_access_schema(conn, db_url)
            row = conn.execute(sql, params).first()
            return row[0] if row else None
    except Exception as e:
        logger.debug("Conversation report-job lookup failed for %s: %s", conversation_id, type(e).__name__)
        return None


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


def count_active_jobs_for_owner(db_url: str, principal: Principal) -> int | None:
    """Count an owner's non-terminal, non-expired jobs.

    Returns ``None`` if the count cannot be computed (e.g. the NAT ``job_info``
    schema differs); callers should fail open so a query mismatch never blocks
    legitimate submissions. Used by the submit-path sandbox concurrency guard.
    """
    try:
        with _job_access_connection(db_url) as conn:
            _ensure_job_access_schema(conn, db_url)
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM job_access ja JOIN job_info ji ON ja.job_id = ji.job_id "
                    "WHERE ja.owner_auth_type = :t AND ja.owner_subject = :s "
                    "AND (ji.is_expired IS NOT TRUE) "
                    f"AND lower(ji.status) NOT IN {_TERMINAL_STATUS_SQL}"
                ),
                {"t": principal.type, "s": principal.sub},
            ).scalar()
            return int(row or 0)
    except Exception as exc:  # noqa: BLE001 - guard must fail open, never block submits
        logger.warning("Could not count active jobs for owner; allowing submit: %s", exc)
        return None


def count_active_jobs_global(db_url: str) -> int | None:
    """Count all non-terminal, non-expired jobs (global capacity guard).

    Returns ``None`` on query failure so callers fail open.
    """
    try:
        with _job_access_connection(db_url) as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM job_info "
                    f"WHERE (is_expired IS NOT TRUE) AND lower(status) NOT IN {_TERMINAL_STATUS_SQL}"
                )
            ).scalar()
            return int(row or 0)
    except Exception as exc:  # noqa: BLE001 - guard must fail open, never block submits
        logger.warning("Could not count active jobs globally; allowing submit: %s", exc)
        return None


def _make_no_auth_principal(owner: str | None = None) -> Principal:
    """Synthesize a principal for deployments with auth disabled (REQUIRE_AUTH=false).

    Uses the middleware caller type as the principal type.  When an owner
    identifier is provided it becomes the subject (useful for programmatic
    job submission); otherwise the caller type is used as a stable subject.
    """
    try:
        from aiq_api.auth.middleware import get_current_user

        current_user = get_current_user()
    except Exception:
        current_user = {}

    principal_type = str(current_user.get("type") or "anonymous")
    subject = owner if owner else principal_type
    email = owner if owner and "@" in owner else None
    return Principal(type=principal_type, sub=subject, email=email)


def require_verified_principal() -> Principal:
    """Return the verified request principal or raise a safe auth error.

    When auth is disabled (REQUIRE_AUTH != true), synthesizes a principal
    from the middleware caller identity so no-auth deployments can still
    access async jobs.
    """
    principal = get_current_principal()
    if principal is not None:
        return principal

    if os.environ.get("REQUIRE_AUTH", "false").lower() == "true":
        raise HTTPException(403, "Verified principal required for async job access")

    return _make_no_auth_principal()


async def authorize_job_access(job_store: Any, db_url: str, job_id: str, principal: Principal) -> Any:
    """Load a job, enforcing ownership when auth is enabled.

    When REQUIRE_AUTH=false, ownership is not enforced — any caller may access
    any existing job.  Ownership records are still written at submit time for
    audit purposes and to support future auth enablement without data migration.
    """
    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if os.environ.get("REQUIRE_AUTH", "false").lower() != "true":
        return job

    loop = asyncio.get_running_loop()
    access = await loop.run_in_executor(None, get_job_access, job_id, db_url)
    if access is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    if not _principal_matches_access(principal, access):
        raise HTTPException(404, f"Job not found: {job_id}")

    return job


def _principal_matches_access(principal: Principal, access: Mapping[str, Any]) -> bool:
    """Return whether a principal matches a job-access row's owner identity."""
    return principal.type == access.get("owner_auth_type") and principal.sub == access.get("owner_subject")


def _job_access_connection(db_url: str):
    """Open a sync connection on the shared event-store engine for the URL."""
    from .event_store import EventStore

    engine = EventStore._get_or_create_sync_engine(db_url)
    return engine.connect()


def _ensure_job_access_schema(conn: Connection, db_url: str) -> None:
    """Create the ``job_access`` table and index once per database URL."""
    if db_url in _job_access_schema_initialized:
        return
    conn.execute(text(_job_access_table_sql(db_url)))
    _ensure_extra_columns(conn, db_url)
    conn.execute(text(_JOB_ACCESS_INDEX_SQL))
    conn.execute(text(_JOB_ACCESS_CONVERSATION_INDEX_SQL))
    _job_access_schema_initialized.add(db_url)


def _ensure_extra_columns(conn: Connection, db_url: str) -> None:
    """Add conversation_id / agent_type to a pre-existing job_access table.

    CREATE TABLE IF NOT EXISTS won't add columns to an existing table. Idempotent across upgrades:
    Postgres supports ADD COLUMN IF NOT EXISTS; SQLite does not, so check PRAGMA table_info first.
    Best-effort — a concurrent add or older engine degrades cleanly.
    """
    try:
        if _is_postgres(db_url):
            for col in ("conversation_id", "agent_type"):
                conn.execute(text(f"ALTER TABLE job_access ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
        else:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(job_access)")).fetchall()}
            for col in ("conversation_id", "agent_type"):
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE job_access ADD COLUMN {col} VARCHAR"))
    except Exception as e:
        logger.debug("Could not ensure job_access extra columns: %s", type(e).__name__)


def _job_access_table_sql(db_url: str) -> str:
    """Return the ``CREATE TABLE`` SQL for ``job_access``, dialect-aware for the URL."""
    created_at_type = (
        "TIMESTAMP WITH TIME ZONE DEFAULT NOW()" if _is_postgres(db_url) else "DATETIME DEFAULT CURRENT_TIMESTAMP"
    )
    return (
        "CREATE TABLE IF NOT EXISTS job_access ("
        "  job_id VARCHAR PRIMARY KEY,"
        "  owner_auth_type VARCHAR NOT NULL,"
        "  owner_subject VARCHAR NOT NULL,"
        "  owner_email VARCHAR,"
        "  conversation_id VARCHAR,"
        "  agent_type VARCHAR,"
        f"  created_at {created_at_type}"
        ")"
    )


def _job_access_upsert_sql(db_url: str):
    """Return the dialect-appropriate upsert statement for ``job_access``."""
    cols = "job_id, owner_auth_type, owner_subject, owner_email, conversation_id, agent_type"
    vals = ":job_id, :owner_auth_type, :owner_subject, :owner_email, :conversation_id, :agent_type"
    postgres_upsert = (
        f"INSERT INTO job_access ({cols}) VALUES ({vals}) "
        "ON CONFLICT(job_id) DO UPDATE SET "
        "owner_auth_type = excluded.owner_auth_type, "
        "owner_subject = excluded.owner_subject, "
        "owner_email = excluded.owner_email, "
        "conversation_id = excluded.conversation_id, "
        "agent_type = excluded.agent_type"
    )
    sqlite_upsert = f"INSERT OR REPLACE INTO job_access ({cols}) VALUES ({vals})"
    return text(postgres_upsert if _is_postgres(db_url) else sqlite_upsert)


def _principal_params(
    job_id: str, principal: Principal, conversation_id: str | None = None, agent_type: str | None = None
) -> dict[str, str | None]:
    """Return SQL bind params for a job's owner identity, conversation, and agent type."""
    return {
        "job_id": job_id,
        "owner_auth_type": principal.type,
        "owner_subject": principal.sub,
        "owner_email": principal.email,
        "conversation_id": conversation_id,
        "agent_type": agent_type,
    }
