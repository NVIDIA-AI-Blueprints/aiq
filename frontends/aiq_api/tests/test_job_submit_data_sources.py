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

"""Tests for async job submit data source targeting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiq_agent.auth import Principal
from aiq_agent.common.data_source_registry import populate_from_config
from aiq_agent.common.data_source_registry import reset_registry


@pytest.fixture(autouse=True)
def data_source_registry():
    """Provide deterministic data sources for submit route validation."""
    reset_registry()
    populate_from_config(
        [
            {
                "id": "web_search",
                "name": "Web Search",
                "description": "Search the web.",
                "tools": ["web_search_tool"],
            },
            {
                "id": "knowledge_layer",
                "name": "Knowledge Base",
                "description": "Search uploaded documents.",
                "tools": ["knowledge_search_tool"],
            },
        ]
    )
    yield
    reset_registry()


@pytest.fixture
async def submit_app(monkeypatch):
    """Build a minimal app with async submit routes and patched side effects."""
    import aiq_agent.auth
    import aiq_api.routes.jobs as jobs_routes

    submitted_job = AsyncMock(return_value="job-1")
    monkeypatch.setattr(jobs_routes, "_start_periodic_cleanup", MagicMock())

    async def _no_op_reaper(*_args, **_kwargs):
        return None

    monkeypatch.setattr(jobs_routes, "_reap_ghost_jobs", _no_op_reaper)
    monkeypatch.setattr(aiq_agent.auth, "get_auth_token", lambda: "token-1")

    from aiq_api.jobs import access
    from aiq_api.jobs import event_store
    from aiq_api.jobs import submit

    monkeypatch.setattr(access, "ensure_job_access_table", MagicMock())
    monkeypatch.setattr(
        access,
        "require_verified_principal",
        lambda: Principal(type="jwt", sub="user-1", email="user@example.com"),
    )
    monkeypatch.setattr(event_store.EventStore, "_ensure_table_exists", MagicMock())
    monkeypatch.setattr(submit, "submit_agent_job", submitted_job)

    worker = SimpleNamespace(
        _dask_available=True,
        _job_store=MagicMock(),
        _scheduler_address="tcp://localhost:8786",
        _db_url="sqlite:///./test.db",
        _config_file_path="config.yml",
        _log_level=20,
        _use_dask_threads=False,
        _front_end_config=SimpleNamespace(expiry_seconds=86400),
    )

    app = FastAPI()
    await jobs_routes.register_job_routes(app, MagicMock(), worker)
    return app, submitted_job


@pytest.mark.asyncio
async def test_submit_job_forwards_selected_data_sources(submit_app):
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={"agent_type": "deep_researcher", "input": "query", "data_sources": ["web_search"]},
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    submitted_job.assert_awaited_once()
    assert submitted_job.await_args.kwargs["data_sources"] == ["web_search"]


@pytest.mark.asyncio
async def test_submit_job_omitted_data_sources_keeps_all_sources(submit_app):
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={"agent_type": "deep_researcher", "input": "query"},
        )

    assert response.status_code == 200
    assert submitted_job.await_args.kwargs["data_sources"] is None


@pytest.mark.asyncio
async def test_submit_job_explicit_null_data_sources_keeps_all_sources(submit_app):
    """Explicit `null` in the JSON body must behave identically to field omission."""
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={"agent_type": "deep_researcher", "input": "query", "data_sources": None},
        )

    assert response.status_code == 200
    assert submitted_job.await_args.kwargs["data_sources"] is None


@pytest.mark.asyncio
async def test_submit_job_forwards_empty_data_sources(submit_app):
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={"agent_type": "deep_researcher", "input": "query", "data_sources": []},
        )

    assert response.status_code == 200
    assert submitted_job.await_args.kwargs["data_sources"] == []


@pytest.mark.asyncio
async def test_submit_job_rejects_unknown_data_sources(submit_app):
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={
                "agent_type": "deep_researcher",
                "input": "query",
                "data_sources": ["does_not_exist", "also_missing"],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "message": "Unknown data source(s): does_not_exist, also_missing",
        "invalid_ids": ["does_not_exist", "also_missing"],
        "known_ids": ["knowledge_layer", "web_search"],
    }
    submitted_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_job_forwards_multiple_data_sources(submit_app):
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={
                "agent_type": "deep_researcher",
                "input": "query",
                "data_sources": ["web_search", "knowledge_layer"],
            },
        )

    assert response.status_code == 200
    assert submitted_job.await_args.kwargs["data_sources"] == ["web_search", "knowledge_layer"]


@pytest.mark.asyncio
async def test_submit_job_mixed_valid_and_unknown_rejects_naming_only_unknown(submit_app):
    app, submitted_job = submit_app

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/async/submit",
            json={
                "agent_type": "deep_researcher",
                "input": "query",
                "data_sources": ["web_search", "does_not_exist"],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "message": "Unknown data source(s): does_not_exist",
        "invalid_ids": ["does_not_exist"],
        "known_ids": ["knowledge_layer", "web_search"],
    }
    submitted_job.assert_not_awaited()
