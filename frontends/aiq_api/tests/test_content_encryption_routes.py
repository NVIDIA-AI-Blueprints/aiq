# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import base64
import json
from datetime import UTC
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aiq_agent.auth import Principal
from aiq_api.jobs import crypto
from aiq_api.registry import AgentConfig


def _static_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


@pytest.fixture(autouse=True)
def clean_encryption_route_env(monkeypatch):
    for name in (
        "AIQ_CONTENT_ENCRYPTION",
        "AIQ_CONTENT_ENCRYPTION_KEY",
        "AIQ_CONTENT_ENCRYPTION_KEY_ID",
        "AIQ_CONTENT_ENCRYPTION_READINESS_TTL_SECONDS",
        "AIQ_CONTENT_ENCRYPTION_DEK_CACHE_TTL_SECONDS",
        "VAULT_ADDR",
        "VAULT_NAMESPACE",
        "VAULT_TRANSIT_MOUNT",
        "VAULT_ROLE_ID",
        "VAULT_SECRET_ID",
        "AIQ_ENCRYPTION_TRANSIT_KEY",
        "VAULT_TIMEOUT_SECONDS",
        "REQUIRE_AUTH",
    ):
        monkeypatch.delenv(name, raising=False)
    crypto.reset_content_encryption_manager_for_tests()
    yield
    crypto.reset_content_encryption_manager_for_tests()


def _enable_static_key(monkeypatch) -> None:
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "key")
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY", _static_key())
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY_ID", "test-key")
    crypto.reset_content_encryption_manager_for_tests()


def _enable_vault(monkeypatch) -> None:
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "vault")
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")
    monkeypatch.setenv("AIQ_ENCRYPTION_TRANSIT_KEY", "reports")
    crypto.reset_content_encryption_manager_for_tests()


async def _build_jobs_app(monkeypatch, tmp_path, *, job_output=None, submitted_job=None) -> FastAPI:
    import aiq_api.routes.jobs as jobs_routes
    from aiq_api.jobs import access
    from aiq_api.jobs import event_store
    from aiq_api.jobs import submit

    monkeypatch.setattr(jobs_routes, "_start_periodic_cleanup", MagicMock())

    async def _no_op_reaper(*_args, **_kwargs):
        return None

    monkeypatch.setattr(jobs_routes, "_reap_ghost_jobs", _no_op_reaper)
    monkeypatch.setattr(
        jobs_routes,
        "require_verified_principal",
        lambda: Principal(type="jwt", sub="user-1", email="user@example.com"),
    )
    monkeypatch.setattr(event_store.EventStore, "_ensure_table_exists", MagicMock())

    if submitted_job is not None:
        monkeypatch.setattr(submit, "submit_agent_job", submitted_job)

    agent_config = AgentConfig(
        class_path="aiq_agent.agents.deep_researcher.agent.DeepResearcherAgent",
        config_name="deep_research_agent",
        description="Test deep researcher",
    )
    monkeypatch.setattr(jobs_routes, "get_agent_config", lambda _agent_type: agent_config)

    job = SimpleNamespace(
        job_id="job-1",
        status="success",
        error=None,
        output=job_output,
        created_at=datetime.now(UTC),
    )
    job_store = SimpleNamespace(get_job=AsyncMock(return_value=job), update_status=AsyncMock())
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}"
    access._job_access_schema_initialized.clear()

    worker = SimpleNamespace(
        _dask_available=True,
        _job_store=job_store,
        _scheduler_address="tcp://localhost:8786",
        _db_url=db_url,
        _config_file_path="config.yml",
        _log_level=20,
        _use_dask_threads=False,
        _front_end_config=SimpleNamespace(expiry_seconds=86400),
    )
    builder = MagicMock()
    builder.get_function_config.return_value = SimpleNamespace(tools=[], exclude_tools=[])
    builder.get_tools = AsyncMock(return_value=[])

    app = FastAPI()
    await jobs_routes.register_job_routes(app, builder, worker)
    return app


@pytest.mark.asyncio
async def test_health_returns_503_when_vault_readiness_failed(monkeypatch, tmp_path):
    _enable_vault(monkeypatch)

    class FailingVault:
        def __init__(self, _config):
            pass

        def generate_data_key(self, *, operation):
            raise crypto.ContentEncryptionUnavailable("vault down")

    monkeypatch.setattr(crypto, "_VaultTransitClient", FailingVault)
    app = await _build_jobs_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["encryption"]["mode"] == "vault"
    assert body["encryption"]["ready"] is False


@pytest.mark.asyncio
async def test_submit_rejects_when_encryption_readiness_failed(monkeypatch, tmp_path):
    _enable_vault(monkeypatch)
    submitted_job = AsyncMock(return_value="job-1")

    class FailingVault:
        def __init__(self, _config):
            pass

        def generate_data_key(self, *, operation):
            raise crypto.ContentEncryptionUnavailable("vault down")

    monkeypatch.setattr(crypto, "_VaultTransitClient", FailingVault)
    app = await _build_jobs_app(monkeypatch, tmp_path, submitted_job=submitted_job)

    with TestClient(app) as client:
        response = client.post("/v1/jobs/async/submit", json={"agent_type": "deep_researcher", "input": "query"})

    assert response.status_code == 503
    submitted_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_authorizes_before_decrypting(monkeypatch, tmp_path):
    _enable_static_key(monkeypatch)
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    app = await _build_jobs_app(monkeypatch, tmp_path, job_output='{"report":"plaintext"}')

    with TestClient(app) as client:
        response = client.get("/v1/jobs/async/job/job-1/report")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_report_returns_500_for_plaintext_violation(monkeypatch, tmp_path):
    _enable_static_key(monkeypatch)
    app = await _build_jobs_app(monkeypatch, tmp_path, job_output='{"report":"plaintext"}')

    with TestClient(app) as client:
        response = client.get("/v1/jobs/async/job/job-1/report")

    assert response.status_code == 500
    assert response.json()["detail"] == "Final report data is invalid"


@pytest.mark.asyncio
async def test_report_returns_500_for_malformed_envelope(monkeypatch, tmp_path):
    _enable_static_key(monkeypatch)
    app = await _build_jobs_app(monkeypatch, tmp_path, job_output="aiqenc:not-json")

    with TestClient(app) as client:
        response = client.get("/v1/jobs/async/job/job-1/report")

    assert response.status_code == 500
    assert response.json()["detail"] == "Final report data is invalid"


@pytest.mark.asyncio
async def test_report_returns_503_when_vault_decrypt_is_unavailable(monkeypatch, tmp_path):
    _enable_vault(monkeypatch)

    class UnwrapFailingVault:
        def __init__(self, _config):
            pass

        def generate_data_key(self, *, operation):
            return b"0" * 32, crypto.WrappedDEK(wrap="vault", kid="transit/reports", wrapped_dek="vault:v1:dek")

        def unwrap_dek(self, wrapped_dek, *, operation):
            raise crypto.ContentEncryptionUnavailable("vault down")

    envelope = crypto.encode_envelope(
        {
            "v": crypto.ENVELOPE_VERSION,
            "alg": crypto.CONTENT_ALGORITHM,
            "wrap": "vault",
            "kid": "transit/reports",
            "aad_hint": crypto.job_output_aad("job-1"),
            "wrapped_dek": "vault:v1:dek",
            "nonce": base64.urlsafe_b64encode(b"1" * 12).decode("ascii").rstrip("="),
            "ciphertext": base64.urlsafe_b64encode(b"ciphertext").decode("ascii").rstrip("="),
            "tag": base64.urlsafe_b64encode(b"2" * 16).decode("ascii").rstrip("="),
        }
    )
    monkeypatch.setattr(crypto, "_VaultTransitClient", UnwrapFailingVault)
    app = await _build_jobs_app(monkeypatch, tmp_path, job_output=envelope)

    with TestClient(app) as client:
        response = client.get("/v1/jobs/async/job/job-1/report")

    assert response.status_code == 503
    assert response.json()["detail"] == "Content encryption is unavailable"


@pytest.mark.asyncio
async def test_report_decrypts_encrypted_final_output(monkeypatch, tmp_path):
    _enable_static_key(monkeypatch)
    stored = crypto.create_job_content_cipher("job-1").encrypt_output_json(json.dumps({"report": "secret"}))
    app = await _build_jobs_app(monkeypatch, tmp_path, job_output=stored)

    with TestClient(app) as client:
        response = client.get("/v1/jobs/async/job/job-1/report")

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-1", "has_report": True, "report": "secret"}
