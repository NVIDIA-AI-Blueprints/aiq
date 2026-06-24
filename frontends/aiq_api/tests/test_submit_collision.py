# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for caller-supplied job_id collision handling in submit_agent_job.

A colliding job_id must NOT trigger the rollback path (which unconditionally
deletes job_info/job_events/job_access for that id), or any caller who knows an
existing job id could destroy that job's durable state.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from aiq_agent.auth import Principal


def _fake_job_store_factory(submit_job):
    class _FakeJobStore:
        def __init__(self, *args, **kwargs):
            pass

        def ensure_job_id(self, job_id):
            return job_id or "generated-id"

        async def submit_job(self, *args, **kwargs):
            return await submit_job(*args, **kwargs)

    return _FakeJobStore


@pytest.fixture
def patched_submit(monkeypatch):
    import aiq_api.jobs.submit as submit_mod
    import nat.front_ends.fastapi.async_jobs.job_store as job_store_mod

    monkeypatch.setenv("NAT_DASK_SCHEDULER_ADDRESS", "tcp://localhost:8786")
    monkeypatch.setenv("REQUIRE_AUTH", "false")

    rollback = MagicMock()
    create_access = MagicMock()
    monkeypatch.setattr(submit_mod, "rollback_job_submission", rollback)
    monkeypatch.setattr(submit_mod, "create_job_access", create_access)
    return submit_mod, job_store_mod, rollback, create_access


@pytest.mark.asyncio
async def test_colliding_job_id_raises_conflict_without_rollback(patched_submit, monkeypatch):
    submit_mod, job_store_mod, rollback, _create_access = patched_submit

    async def _submit_job_collision(*args, **kwargs):
        raise IntegrityError("INSERT INTO job_info", {}, Exception("UNIQUE constraint failed: job_info.job_id"))

    monkeypatch.setattr(job_store_mod, "JobStore", _fake_job_store_factory(_submit_job_collision))

    with pytest.raises(submit_mod.JobIdConflictError):
        await submit_mod.submit_agent_job(
            agent_type="deep_researcher",
            input_text="hello",
            owner="user@example.com",
            principal=Principal(type="jwt", sub="user-1", email="user@example.com"),
            job_id="victim-job-id",
        )

    # The colliding job already existed and is NOT ours — we must never delete it.
    rollback.assert_not_called()


@pytest.mark.asyncio
async def test_access_persistence_failure_still_rolls_back(patched_submit, monkeypatch):
    submit_mod, job_store_mod, rollback, create_access = patched_submit

    async def _submit_job_ok(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(job_store_mod, "JobStore", _fake_job_store_factory(_submit_job_ok))
    # create_job_access runs in an executor; make it raise to simulate access persistence failure.
    create_access.side_effect = RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await submit_mod.submit_agent_job(
            agent_type="deep_researcher",
            input_text="hello",
            owner="user@example.com",
            principal=Principal(type="jwt", sub="user-1", email="user@example.com"),
            job_id="our-own-new-job",
        )

    # We created this job, then access persistence failed -> roll back our partial state.
    rollback.assert_called_once()


@pytest.mark.asyncio
async def test_post_create_submit_failure_rolls_back(patched_submit, monkeypatch):
    """A non-collision submit_job failure (e.g. scheduler/Dask error) after the job_info
    row is committed must still roll back, or it leaves an orphaned ownerless job."""
    submit_mod, job_store_mod, rollback, _create_access = patched_submit

    async def _submit_job_dask_failure(*args, **kwargs):
        # NAT's submit_job commits job_info before submitting to Dask, so this
        # mirrors a Variable.set timeout / scheduler-unreachable error that fires
        # AFTER the row exists.
        raise RuntimeError("Task abc-job unknown to scheduler.")

    monkeypatch.setattr(job_store_mod, "JobStore", _fake_job_store_factory(_submit_job_dask_failure))

    with pytest.raises(RuntimeError):
        await submit_mod.submit_agent_job(
            agent_type="deep_researcher",
            input_text="hello",
            owner="user@example.com",
            principal=Principal(type="jwt", sub="user-1", email="user@example.com"),
            job_id="our-own-new-job",
        )

    rollback.assert_called_once()


@pytest.mark.asyncio
async def test_submit_records_conversation_id_on_job_access(patched_submit, monkeypatch):
    """The originating conversation id is persisted with the job for report-follow-up lookups."""
    submit_mod, job_store_mod, _rollback, create_access = patched_submit

    async def _submit_job_ok(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(job_store_mod, "JobStore", _fake_job_store_factory(_submit_job_ok))
    monkeypatch.setattr(submit_mod, "_current_conversation_id", lambda: "conv-XYZ")

    await submit_mod.submit_agent_job(
        agent_type="deep_researcher",
        input_text="hello",
        owner="user@example.com",
        principal=Principal(type="jwt", sub="user-1", email="user@example.com"),
        job_id="job-1",
    )

    create_access.assert_called_once()
    # create_job_access(job_id, principal, db_url, conversation_id) -> conversation id is the 4th positional arg
    assert create_access.call_args.args[0] == "job-1"
    assert create_access.call_args.args[3] == "conv-XYZ"
