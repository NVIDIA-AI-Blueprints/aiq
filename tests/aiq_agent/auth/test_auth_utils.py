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

"""Tests for auth utilities: token fetcher registry and user info extraction.

Module under test: src/aiq_agent/auth/utils.py
"""

import base64
import json

import pytest

from aiq_agent.auth import clear_token_fetchers
from aiq_agent.auth import get_auth_token
from aiq_agent.auth import get_current_user_info
from aiq_agent.auth import register_token_fetcher


def _make_jwt(payload: dict) -> str:
    """Build a minimal unsigned JWT (header.payload.signature) for testing."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


@pytest.fixture(autouse=True)
def _isolate_fetchers():
    """Ensure each test starts and ends with a clean fetcher registry."""
    clear_token_fetchers()
    yield
    clear_token_fetchers()


def test_get_auth_token_default_returns_none():
    """With no fetchers registered and no Context, get_auth_token returns None."""
    assert get_auth_token() is None


def test_register_token_fetcher_basic():
    """A registered fetcher that returns a token is used by get_auth_token."""
    register_token_fetcher(lambda: "my-token")
    assert get_auth_token() == "my-token"


def test_register_token_fetcher_priority():
    """Higher-priority fetcher wins over lower-priority one."""
    register_token_fetcher(lambda: "low", priority=1)
    register_token_fetcher(lambda: "high", priority=10)
    assert get_auth_token() == "high"


def test_register_token_fetcher_skips_none():
    """A fetcher returning None is skipped; the next fetcher is tried."""
    register_token_fetcher(lambda: None, priority=10)
    register_token_fetcher(lambda: "fallback", priority=5)
    assert get_auth_token() == "fallback"


def test_register_token_fetcher_skips_exceptions():
    """A fetcher that raises is skipped; the next fetcher is tried."""

    def bad_fetcher():
        raise RuntimeError("boom")

    register_token_fetcher(bad_fetcher, priority=10)
    register_token_fetcher(lambda: "ok", priority=5)
    assert get_auth_token() == "ok"


def test_clear_token_fetchers():
    """After clearing, no registered fetchers remain and default behavior is restored."""
    register_token_fetcher(lambda: "token")
    assert get_auth_token() == "token"

    clear_token_fetchers()
    assert get_auth_token() is None


def test_get_current_user_info_uses_registered_fetcher():
    """get_current_user_info delegates to get_auth_token, which uses registered fetchers."""
    jwt = _make_jwt({"email": "alice@nvidia.com", "name": "Alice"})
    register_token_fetcher(lambda: jwt)

    user_info = get_current_user_info()
    assert user_info is not None
    assert user_info.email == "alice@nvidia.com"
    assert user_info.name == "Alice"


def test_register_token_fetcher_deduplication():
    """Registering the same fetcher twice is a no-op (identity check)."""
    call_count = 0

    def my_fetcher():
        nonlocal call_count
        call_count += 1
        return "token"

    register_token_fetcher(my_fetcher, priority=5)
    register_token_fetcher(my_fetcher, priority=10)  # duplicate — ignored

    assert get_auth_token() == "token"
    assert call_count == 1  # called only once, not twice
