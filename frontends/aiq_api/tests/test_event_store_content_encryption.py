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

import pytest
from sqlalchemy import text

from aiq_api.jobs import crypto
from aiq_api.jobs.event_store import EventStore


def _static_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


@pytest.fixture(autouse=True)
def clean_encryption_env(monkeypatch):
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
    EventStore._tables_initialized.clear()
    crypto.reset_content_encryption_manager_for_tests()
    yield
    EventStore._tables_initialized.clear()
    crypto.reset_content_encryption_manager_for_tests()


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path / 'events.db'}"


def _enable_static_key(monkeypatch) -> None:
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION", "key")
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY", _static_key())
    monkeypatch.setenv("AIQ_CONTENT_ENCRYPTION_KEY_ID", "test-key")
    crypto.reset_content_encryption_manager_for_tests()


def _raw_event_data(db_url: str) -> dict:
    engine = EventStore._get_or_create_sync_engine(db_url)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT event_data FROM job_events ORDER BY id DESC LIMIT 1")).fetchone()
    assert row is not None
    return json.loads(row[0])


def test_output_artifact_content_is_encrypted_at_rest_and_decrypted_on_read(monkeypatch, db_url):
    _enable_static_key(monkeypatch)
    cipher = crypto.create_job_content_cipher("job-1")
    store = EventStore(db_url, "job-1", content_cipher=cipher)

    store.store(
        {
            "type": "artifact.update",
            "data": {
                "type": "output",
                "content": "secret report",
                "output_category": "final_report",
            },
        }
    )

    raw_event = _raw_event_data(db_url)
    raw_content = raw_event["data"]["content"]
    assert raw_event["data"]["type"] == "output"
    assert raw_event["data"]["output_category"] == "final_report"
    assert raw_content[crypto.ENCRYPTED_FIELD_MARKER] is True
    assert raw_content[crypto.ENCRYPTED_FIELD_VALUE].startswith(crypto.ENVELOPE_PREFIX)
    assert "secret report" not in json.dumps(raw_event)

    events = EventStore.get_events(db_url, "job-1")
    assert events[0]["data"]["content"] == "secret report"


def test_file_artifact_content_is_encrypted_in_batch(monkeypatch, db_url):
    _enable_static_key(monkeypatch)
    cipher = crypto.create_job_content_cipher("job-1")
    store = EventStore(db_url, "job-1", content_cipher=cipher)

    store.store_batch(
        [
            {
                "type": "artifact.update",
                "data": {
                    "type": "file",
                    "content": "secret file content",
                    "file_path": "/shared/output.md",
                },
            }
        ]
    )

    raw_event = _raw_event_data(db_url)
    assert raw_event["data"]["content"][crypto.ENCRYPTED_FIELD_VALUE].startswith(crypto.ENVELOPE_PREFIX)
    assert "secret file content" not in json.dumps(raw_event)

    events = EventStore.get_events(db_url, "job-1")
    assert events[0]["data"]["content"] == "secret file content"


def test_non_sensitive_artifact_content_remains_plaintext(monkeypatch, db_url):
    _enable_static_key(monkeypatch)
    cipher = crypto.create_job_content_cipher("job-1")
    store = EventStore(db_url, "job-1", content_cipher=cipher)

    store.store(
        {
            "type": "artifact.update",
            "data": {
                "type": "citation_source",
                "content": "https://example.com/source",
                "url": "https://example.com/source",
            },
        }
    )

    raw_event = _raw_event_data(db_url)
    assert raw_event["data"]["content"] == "https://example.com/source"


def test_plaintext_historical_event_rows_still_read_in_encrypted_mode(monkeypatch, db_url):
    _enable_static_key(monkeypatch)
    store = EventStore(db_url, "job-1")

    store.store(
        {
            "type": "artifact.update",
            "data": {
                "type": "output",
                "content": "historical plaintext",
            },
        }
    )

    events = EventStore.get_events(db_url, "job-1")
    assert events[0]["data"]["content"] == "historical plaintext"


@pytest.mark.asyncio
async def test_async_event_reads_decrypt_content(monkeypatch, db_url):
    _enable_static_key(monkeypatch)
    cipher = crypto.create_job_content_cipher("job-1")
    store = EventStore(db_url, "job-1", content_cipher=cipher)
    store.store(
        {
            "type": "artifact.update",
            "data": {
                "type": "output",
                "content": "async secret report",
            },
        }
    )

    events = await EventStore.get_events_async(db_url, "job-1")

    assert events[0]["data"]["content"] == "async secret report"
