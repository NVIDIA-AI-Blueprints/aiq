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
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiq_api.jobs import crypto


def _static_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


def _real_vault_env_present() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "VAULT_ADDR",
            "VAULT_ROLE_ID",
            "VAULT_SECRET_ID",
            "AIQ_ENCRYPTION_TRANSIT_KEY",
        )
    )


@pytest.fixture(autouse=True)
def clean_encryption_env(monkeypatch, request):
    if request.node.name == "test_real_vault_transit_round_trip":
        crypto.reset_content_encryption_manager_for_tests()
        yield
        crypto.reset_content_encryption_manager_for_tests()
        return

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
    ):
        monkeypatch.delenv(name, raising=False)
    crypto.reset_content_encryption_manager_for_tests()
    yield
    crypto.reset_content_encryption_manager_for_tests()


def _enable_static_key(monkeypatch, *, cache_ttl: str | None = None) -> None:
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "key")
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY", _static_key())
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY_ID", "test-key")
    if cache_ttl is not None:
        monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_DEK_CACHE_TTL_SECONDS", cache_ttl)
    crypto.reset_content_encryption_manager_for_tests()


def test_static_key_envelope_round_trip(monkeypatch):
    _enable_static_key(monkeypatch)

    cipher = crypto.create_job_content_cipher("job-1")
    stored = cipher.encrypt_output_json('{"report":"secret report"}')

    assert stored.startswith(crypto.ENVELOPE_PREFIX)
    assert "secret report" not in stored
    assert crypto.read_job_output("job-1", stored) == {"report": "secret report"}


def test_aad_mismatch_fails(monkeypatch):
    _enable_static_key(monkeypatch)

    stored = crypto.create_job_content_cipher("job-1").encrypt_output_json('{"report":"secret"}')

    with pytest.raises(crypto.ContentEncryptionInvalidData):
        crypto.read_job_output("job-2", stored)


def test_tamper_fails(monkeypatch):
    _enable_static_key(monkeypatch)

    stored = crypto.create_job_content_cipher("job-1").encrypt_output_json('{"report":"secret"}')
    envelope = crypto.decode_envelope(stored)
    padding = "=" * (-len(envelope["ciphertext"]) % 4)
    ciphertext = bytearray(base64.urlsafe_b64decode(envelope["ciphertext"] + padding))
    ciphertext[0] ^= 0x01
    envelope["ciphertext"] = base64.urlsafe_b64encode(bytes(ciphertext)).decode("ascii").rstrip("=")
    tampered = crypto.encode_envelope(envelope)

    with pytest.raises(crypto.ContentEncryptionInvalidData):
        crypto.read_job_output("job-1", tampered)


def test_plaintext_job_output_is_rejected_in_encrypted_mode(monkeypatch):
    _enable_static_key(monkeypatch)

    with pytest.raises(crypto.ContentEncryptionPlaintextViolation):
        crypto.read_job_output("job-1", '{"report":"plaintext"}')


def test_off_mode_preserves_current_behavior_and_does_not_decrypt_envelopes(monkeypatch):
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "off")
    crypto.reset_content_encryption_manager_for_tests()

    assert crypto.read_job_output("job-1", '{"report":"plaintext"}') == {"report": "plaintext"}
    assert crypto.read_job_output("job-1", "aiqenc:not-json") == "aiqenc:not-json"


@pytest.mark.asyncio
async def test_update_job_output_encrypts_entire_payload(monkeypatch):
    _enable_static_key(monkeypatch)
    cipher = crypto.create_job_content_cipher("job-1")
    job_store = SimpleNamespace(update_status=AsyncMock())

    await crypto.update_job_output(job_store, "job-1", "success", output={"report": "secret"}, cipher=cipher)

    stored = job_store.update_status.await_args.kwargs["output"]
    assert stored.startswith(crypto.ENVELOPE_PREFIX)
    assert "secret" not in stored
    assert crypto.read_job_output("job-1", stored) == {"report": "secret"}


@pytest.mark.asyncio
async def test_sqlite_job_store_persists_encrypted_output(monkeypatch, tmp_path):
    from nat.front_ends.fastapi.async_jobs.job_store import Base
    from nat.front_ends.fastapi.async_jobs.job_store import JobStatus
    from nat.front_ends.fastapi.async_jobs.job_store import JobStore
    from nat.front_ends.fastapi.async_jobs.job_store import get_db_engine

    _enable_static_key(monkeypatch)
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}"
    engine = get_db_engine(db_url, use_async=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    job_store = JobStore(scheduler_address="tcp://localhost:8786", db_engine=engine)
    await job_store._create_job(job_id="job-1")
    cipher = crypto.create_job_content_cipher("job-1")

    await crypto.update_job_output(job_store, "job-1", JobStatus.SUCCESS, output={"report": "secret"}, cipher=cipher)
    job = await job_store.get_job("job-1")

    assert job.output.startswith(crypto.ENVELOPE_PREFIX)
    assert "secret" not in job.output
    assert crypto.read_job_output("job-1", job.output) == {"report": "secret"}
    await engine.dispose()


def test_static_key_invalid_config_fails_hard(monkeypatch):
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "key")
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY", "not a 32 byte base64 key")

    with pytest.raises(crypto.ContentEncryptionConfigError):
        crypto.get_content_encryption_config()


def test_large_report_round_trip(monkeypatch):
    _enable_static_key(monkeypatch)
    report = "large report\n" * 100_000

    stored = crypto.create_job_content_cipher("job-large").encrypt_output_json(json.dumps({"report": report}))

    assert crypto.read_job_output("job-large", stored)["report"] == report


def test_dek_cache_reuses_unwrapped_dek(monkeypatch):
    _enable_static_key(monkeypatch)
    manager = crypto.get_content_encryption_manager()
    stored = manager.create_job_cipher("job-1").encrypt_output_json('{"report":"secret"}')
    calls = 0
    original = manager._unwrap_dek_with_static_key

    def counted_unwrap(envelope):
        nonlocal calls
        calls += 1
        return original(envelope)

    monkeypatch.setattr(manager, "_unwrap_dek_with_static_key", counted_unwrap)

    assert manager.decrypt_job_output_text("job-1", stored) == '{"report":"secret"}'
    assert manager.decrypt_job_output_text("job-1", stored) == '{"report":"secret"}'
    assert calls == 1


def test_dek_cache_can_be_disabled(monkeypatch):
    _enable_static_key(monkeypatch, cache_ttl="0")
    manager = crypto.get_content_encryption_manager()
    stored = manager.create_job_cipher("job-1").encrypt_output_json('{"report":"secret"}')
    calls = 0
    original = manager._unwrap_dek_with_static_key

    def counted_unwrap(envelope):
        nonlocal calls
        calls += 1
        return original(envelope)

    monkeypatch.setattr(manager, "_unwrap_dek_with_static_key", counted_unwrap)

    assert manager.decrypt_job_output_text("job-1", stored) == '{"report":"secret"}'
    assert manager.decrypt_job_output_text("job-1", stored) == '{"report":"secret"}'
    assert calls == 2


def test_dek_cache_evicts_lru_when_max_entries_is_exceeded():
    cache = crypto._DEKCache(ttl_seconds=60, max_entries=2)

    cache.put("first", b"1" * 32)
    cache.put("second", b"2" * 32)
    assert cache.get("first") == b"1" * 32
    cache.put("third", b"3" * 32)

    assert cache.get("second") is None
    assert cache.get("first") == b"1" * 32
    assert cache.get("third") == b"3" * 32


def test_vault_missing_required_config_fails_startup(monkeypatch):
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "vault")
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")

    with pytest.raises(crypto.ContentEncryptionConfigError, match="AIQ_ENCRYPTION_TRANSIT_KEY"):
        crypto.get_content_encryption_config()


def test_vault_operational_failure_starts_unhealthy_and_uses_readiness_cache(monkeypatch):
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "vault")
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")
    monkeypatch.setenv("AIQ_ENCRYPTION_TRANSIT_KEY", "reports")
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_READINESS_TTL_SECONDS", "60")
    calls = 0

    class FailingVault:
        def __init__(self, _config):
            pass

        def generate_data_key(self, *, operation):
            nonlocal calls
            calls += 1
            raise crypto.ContentEncryptionUnavailable("vault down")

    monkeypatch.setattr(crypto, "_VaultTransitClient", FailingVault)
    crypto.reset_content_encryption_manager_for_tests()

    startup = crypto.validate_content_encryption_startup()
    health = crypto.get_content_encryption_health()

    assert startup.ready is False
    assert health.ready is False
    assert calls == 1


def test_vault_readiness_rechecks_when_cache_is_stale(monkeypatch):
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "vault")
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")
    monkeypatch.setenv("AIQ_ENCRYPTION_TRANSIT_KEY", "reports")
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_READINESS_TTL_SECONDS", "0")
    calls = 0

    class FailingVault:
        def __init__(self, _config):
            pass

        def generate_data_key(self, *, operation):
            nonlocal calls
            calls += 1
            raise crypto.ContentEncryptionUnavailable("vault down")

    monkeypatch.setattr(crypto, "_VaultTransitClient", FailingVault)
    crypto.reset_content_encryption_manager_for_tests()

    crypto.validate_content_encryption_startup()
    crypto.get_content_encryption_health()

    assert calls == 2


@pytest.mark.skipif(not _real_vault_env_present(), reason="real Vault Transit credentials are not configured")
def test_real_vault_transit_round_trip(monkeypatch):
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "vault")
    crypto.reset_content_encryption_manager_for_tests()

    readiness = crypto.validate_content_encryption_startup()
    stored = crypto.create_job_content_cipher("job-real-vault").encrypt_output_json('{"report":"secret"}')

    assert readiness.ready is True
    assert stored.startswith(crypto.ENVELOPE_PREFIX)
    assert "secret" not in stored
    assert crypto.read_job_output("job-real-vault", stored) == {"report": "secret"}
