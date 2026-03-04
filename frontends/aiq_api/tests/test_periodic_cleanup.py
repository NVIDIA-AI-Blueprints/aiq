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

"""Tests for periodic cleanup of expired jobs and old events."""

from __future__ import annotations

import asyncio
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from aiq_api.jobs.event_store import EventStore


@pytest.fixture
def db_url(tmp_path):
    """Return an async SQLite database URL."""
    return f"sqlite+aiosqlite:///{tmp_path / 'test_cleanup.db'}"


@pytest.fixture(autouse=True)
def clear_event_store_caches():
    """Clear EventStore caches between tests."""
    EventStore._tables_initialized.clear()
    yield
    EventStore._tables_initialized.clear()


def _backdate_events(db_url: str, hours: int, *, job_id: str | None = None, event_id: int | None = None):
    """Helper to backdate events in the test DB."""
    from sqlalchemy import text

    engine = EventStore._get_or_create_sync_engine(db_url)
    old_time = datetime.now(UTC) - timedelta(hours=hours)
    with engine.connect() as conn:
        params: dict = {"ts": old_time.replace(tzinfo=None)}
        if event_id is not None:
            query = "UPDATE job_events SET created_at = :ts WHERE id = :event_id"
            params["event_id"] = event_id
        elif job_id is not None:
            query = "UPDATE job_events SET created_at = :ts WHERE job_id = :job_id"
            params["job_id"] = job_id
        else:
            query = "UPDATE job_events SET created_at = :ts"
        conn.execute(text(query), params)
        conn.commit()


def _create_expired_job(db_url: str, job_id: str):
    """Helper to create a fake expired job in the job_info table."""
    from sqlalchemy import text

    engine = EventStore._get_or_create_sync_engine(db_url)
    with engine.connect() as conn:
        # Ensure job_info table exists (simplified schema for tests)
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
        conn.execute(
            text(
                "INSERT OR REPLACE INTO job_info "
                "(job_id, status, expiry_seconds, is_expired, created_at, updated_at) "
                "VALUES (:job_id, 'success', 3600, :is_expired, :ts, :ts)"
            ),
            {
                "job_id": job_id,
                "is_expired": True,
                "ts": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        conn.commit()


# =========================================================================
# EventStore.cleanup_old_events (time-based)
# =========================================================================


class TestCleanupOldEvents:
    """Tests for EventStore.cleanup_old_events."""

    def test_cleanup_deletes_old_events(self, db_url):
        """Events older than retention period should be deleted."""
        store = EventStore(db_url, job_id="job-1")
        store.store({"type": "test.event", "data": {"msg": "hello"}})
        store.store({"type": "test.event", "data": {"msg": "world"}})

        _backdate_events(db_url, hours=2)

        deleted = EventStore.cleanup_old_events(db_url, retention_seconds=3600)
        assert deleted == 2
        assert len(EventStore.get_events(db_url, "job-1")) == 0

    def test_cleanup_preserves_recent_events(self, db_url):
        """Events within retention period should not be deleted."""
        store = EventStore(db_url, job_id="job-1")
        store.store({"type": "test.event", "data": {"msg": "recent"}})

        deleted = EventStore.cleanup_old_events(db_url, retention_seconds=3600)
        assert deleted == 0
        assert len(EventStore.get_events(db_url, "job-1")) == 1

    def test_cleanup_mixed_old_and_new(self, db_url):
        """Only old events should be deleted when both old and new exist."""
        store = EventStore(db_url, job_id="job-1")
        store.store({"type": "old.event", "data": {"msg": "old"}})
        store.store({"type": "new.event", "data": {"msg": "new"}})

        _backdate_events(db_url, hours=2, event_id=1)

        deleted = EventStore.cleanup_old_events(db_url, retention_seconds=3600)
        assert deleted == 1
        assert len(EventStore.get_events(db_url, "job-1")) == 1

    def test_cleanup_multiple_jobs(self, db_url):
        """Cleanup should delete old events across all jobs."""
        EventStore(db_url, job_id="job-1").store({"type": "test", "data": {}})
        EventStore(db_url, job_id="job-2").store({"type": "test", "data": {}})

        _backdate_events(db_url, hours=2)

        deleted = EventStore.cleanup_old_events(db_url, retention_seconds=3600)
        assert deleted == 2

    def test_cleanup_empty_table(self, db_url):
        """Cleanup on empty table should return 0."""
        EventStore(db_url, job_id="job-1")  # ensures table exists
        assert EventStore.cleanup_old_events(db_url, retention_seconds=3600) == 0


class TestCleanupOldEventsAsync:
    """Tests for EventStore.cleanup_old_events_async."""

    @pytest.mark.asyncio
    async def test_async_cleanup_delegates_to_sync(self, db_url):
        """Async cleanup should produce same results as sync."""
        store = EventStore(db_url, job_id="job-1")
        store.store({"type": "test", "data": {}})
        _backdate_events(db_url, hours=2)

        deleted = await EventStore.cleanup_old_events_async(db_url, retention_seconds=3600)
        assert deleted == 1


class TestCleanupJobEvents:
    """Tests for EventStore.cleanup_job_events (targeted per-job deletion)."""

    def test_cleanup_specific_job(self, db_url):
        """Should delete events for a specific job only."""
        EventStore(db_url, job_id="job-1").store({"type": "test", "data": {}})
        EventStore(db_url, job_id="job-1").store({"type": "test", "data": {}})
        EventStore(db_url, job_id="job-2").store({"type": "test", "data": {}})

        deleted = EventStore.cleanup_job_events(db_url, "job-1")
        assert deleted == 2
        assert len(EventStore.get_events(db_url, "job-2")) == 1


# =========================================================================
# _run_event_cleanup (coordinated: time-based + expired-job events)
# =========================================================================


class TestRunEventCleanup:
    """Tests for _run_event_cleanup coordinated cleanup cycle."""

    @pytest.mark.asyncio
    async def test_removes_events_for_expired_jobs(self, db_url):
        """Events for jobs marked is_expired=True in job_info should be deleted."""
        from aiq_api.routes.jobs import _run_event_cleanup

        store = EventStore(db_url, job_id="expired-job")
        store.store({"type": "test", "data": {"msg": "should be deleted"}})

        _create_expired_job(db_url, "expired-job")

        await _run_event_cleanup(db_url, retention_seconds=86400, is_postgres=False)

        remaining = EventStore.get_events(db_url, "expired-job")
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_preserves_events_for_non_expired_jobs(self, db_url):
        """Events for jobs NOT marked expired should be preserved (if within retention)."""
        from aiq_api.routes.jobs import _run_event_cleanup

        store = EventStore(db_url, job_id="active-job")
        store.store({"type": "test", "data": {"msg": "keep me"}})

        # Create job_info table but no expired jobs
        _create_expired_job(db_url, "some-other-job")

        await _run_event_cleanup(db_url, retention_seconds=86400, is_postgres=False)

        remaining = EventStore.get_events(db_url, "active-job")
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_combined_time_and_expired_cleanup(self, db_url):
        """Both time-based and expired-job cleanup should run in one cycle."""
        from aiq_api.routes.jobs import _run_event_cleanup

        # Old event for a non-expired job (should be cleaned by time)
        store1 = EventStore(db_url, job_id="old-job")
        store1.store({"type": "test", "data": {}})
        _backdate_events(db_url, hours=2, job_id="old-job")

        # Recent event for an expired job (should be cleaned by expired-job logic)
        store2 = EventStore(db_url, job_id="expired-job")
        store2.store({"type": "test", "data": {}})
        _create_expired_job(db_url, "expired-job")

        # Recent event for a live job (should survive)
        store3 = EventStore(db_url, job_id="live-job")
        store3.store({"type": "test", "data": {}})

        await _run_event_cleanup(db_url, retention_seconds=3600, is_postgres=False)

        assert len(EventStore.get_events(db_url, "old-job")) == 0
        assert len(EventStore.get_events(db_url, "expired-job")) == 0
        assert len(EventStore.get_events(db_url, "live-job")) == 1


# =========================================================================
# _cleanup_old_events_loop (background task)
# =========================================================================


class TestCleanupOldEventsLoop:
    """Tests for _cleanup_old_events_loop background task."""

    @pytest.mark.asyncio
    async def test_runs_immediately_on_startup(self):
        """The loop should run one cleanup cycle before the first sleep."""
        from aiq_api.routes.jobs import _cleanup_old_events_loop

        calls = []

        async def mock_run(db_url, retention_seconds, is_postgres):
            calls.append(("run", retention_seconds))
            if len(calls) >= 2:
                raise asyncio.CancelledError()

        with patch("aiq_api.routes.jobs._run_event_cleanup", side_effect=mock_run):
            task = asyncio.create_task(
                _cleanup_old_events_loop(
                    db_url="sqlite+aiosqlite:///test.db",
                    retention_seconds=3600,
                    interval_seconds=9999,  # long interval — shouldn't matter if startup run works
                )
            )
            # Give the startup run time to execute
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(calls) >= 1, "Should have run at least once immediately on startup"

    @pytest.mark.asyncio
    async def test_loop_survives_cleanup_errors(self):
        """The loop should continue running even if cleanup raises."""
        from aiq_api.routes.jobs import _cleanup_old_events_loop

        call_count = 0

        async def mock_run(db_url, retention_seconds, is_postgres):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                pass  # startup run — succeeds
            elif call_count == 2:
                raise RuntimeError("DB connection failed")
            elif call_count >= 4:
                raise asyncio.CancelledError()

        with patch("aiq_api.routes.jobs._run_event_cleanup", side_effect=mock_run):
            task = asyncio.create_task(
                _cleanup_old_events_loop(
                    db_url="sqlite+aiosqlite:///test.db",
                    retention_seconds=3600,
                    interval_seconds=0,
                )
            )
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        assert call_count >= 3, "Should have continued past the error"


# =========================================================================
# _start_periodic_cleanup (orchestration)
# =========================================================================


class TestStartPeriodicCleanup:
    """Tests for _start_periodic_cleanup orchestration function."""

    def test_submits_dask_cleanup_task(self):
        """Should submit NAT's periodic_cleanup to Dask."""
        from aiq_api.routes.jobs import _start_periodic_cleanup

        mock_job_store = MagicMock()
        mock_future = MagicMock()
        mock_job_store.dask_client.submit.return_value = mock_future

        with patch("aiq_api.routes.jobs.asyncio.create_task"):
            with patch("dask.distributed.fire_and_forget") as mock_faf:
                _start_periodic_cleanup(
                    job_store=mock_job_store,
                    scheduler_address="tcp://localhost:8786",
                    db_url="sqlite:///test.db",
                    expiry_seconds=3600,
                    log_level=20,
                    use_threads=False,
                )

        mock_job_store.dask_client.submit.assert_called_once()
        call_kwargs = mock_job_store.dask_client.submit.call_args[1]
        assert call_kwargs["scheduler_address"] == "tcp://localhost:8786"
        assert call_kwargs["db_url"] == "sqlite:///test.db"
        assert call_kwargs["sleep_time_sec"] == 1800  # 3600 // 2
        mock_faf.assert_called_once_with(mock_future)

    def test_starts_event_cleanup_task(self):
        """Should start a local asyncio task for event cleanup."""
        from aiq_api.routes.jobs import _start_periodic_cleanup

        mock_job_store = MagicMock()
        mock_job_store.dask_client.submit.return_value = MagicMock()

        with patch("aiq_api.routes.jobs.asyncio.create_task") as mock_create_task:
            with patch("dask.distributed.fire_and_forget"):
                _start_periodic_cleanup(
                    job_store=mock_job_store,
                    scheduler_address="tcp://localhost:8786",
                    db_url="sqlite:///test.db",
                    expiry_seconds=7200,
                    log_level=20,
                    use_threads=False,
                )

        mock_create_task.assert_called_once()

    def test_cleanup_interval_clamped_max(self):
        """Cleanup interval should be clamped to 3600s max."""
        from aiq_api.routes.jobs import _start_periodic_cleanup

        mock_job_store = MagicMock()
        mock_job_store.dask_client.submit.return_value = MagicMock()

        with patch("aiq_api.routes.jobs.asyncio.create_task"):
            with patch("dask.distributed.fire_and_forget"):
                _start_periodic_cleanup(
                    job_store=mock_job_store,
                    scheduler_address="tcp://localhost:8786",
                    db_url="sqlite:///test.db",
                    expiry_seconds=604800,  # 7 days
                    log_level=20,
                    use_threads=False,
                )

        call_kwargs = mock_job_store.dask_client.submit.call_args[1]
        assert call_kwargs["sleep_time_sec"] == 3600

    def test_cleanup_interval_clamped_min(self):
        """Cleanup interval should be at least 60s."""
        from aiq_api.routes.jobs import _start_periodic_cleanup

        mock_job_store = MagicMock()
        mock_job_store.dask_client.submit.return_value = MagicMock()

        with patch("aiq_api.routes.jobs.asyncio.create_task"):
            with patch("dask.distributed.fire_and_forget"):
                _start_periodic_cleanup(
                    job_store=mock_job_store,
                    scheduler_address="tcp://localhost:8786",
                    db_url="sqlite:///test.db",
                    expiry_seconds=60,
                    log_level=20,
                    use_threads=False,
                )

        call_kwargs = mock_job_store.dask_client.submit.call_args[1]
        assert call_kwargs["sleep_time_sec"] == 60

    def test_dask_submit_failure_doesnt_block_event_cleanup(self):
        """If Dask submit fails, event cleanup should still start."""
        from aiq_api.routes.jobs import _start_periodic_cleanup

        mock_job_store = MagicMock()
        mock_job_store.dask_client.submit.side_effect = RuntimeError("Dask unavailable")

        with patch("aiq_api.routes.jobs.asyncio.create_task") as mock_create_task:
            _start_periodic_cleanup(
                job_store=mock_job_store,
                scheduler_address="tcp://localhost:8786",
                db_url="sqlite:///test.db",
                expiry_seconds=3600,
                log_level=20,
                use_threads=False,
            )

        mock_create_task.assert_called_once()


# =========================================================================
# stop_periodic_cleanup (graceful shutdown)
# =========================================================================


class TestStopPeriodicCleanup:
    """Tests for stop_periodic_cleanup shutdown function."""

    @pytest.mark.asyncio
    async def test_cancels_running_task(self):
        """Should cancel the background cleanup task."""
        import aiq_api.routes.jobs as jobs_module

        async def long_running():
            await asyncio.sleep(9999)

        jobs_module._cleanup_task = asyncio.create_task(long_running())
        assert not jobs_module._cleanup_task.done()

        await jobs_module.stop_periodic_cleanup()

        assert jobs_module._cleanup_task is None

    @pytest.mark.asyncio
    async def test_noop_when_no_task(self):
        """Should not raise if no task is running."""
        import aiq_api.routes.jobs as jobs_module

        jobs_module._cleanup_task = None
        await jobs_module.stop_periodic_cleanup()  # should not raise
