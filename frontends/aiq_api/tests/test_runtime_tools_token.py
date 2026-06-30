# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from unittest.mock import patch

from pydantic import SecretStr

from aiq_api.mcp_auth import runtime_tools
from nat.authentication.token_storage import InMemoryTokenStorage
from nat.builder.context import ContextState
from nat.data_models.authentication import AuthResult
from nat.data_models.authentication import BearerTokenCred

USER = "verified:alice"


def _auth(*, expired: bool) -> AuthResult:
    delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    return AuthResult(
        credentials=[BearerTokenCred(token=SecretStr("tok"))],
        token_expires_at=datetime.now(UTC) + delta,
    )


async def _check(stored: AuthResult | None) -> tuple[bool, bool]:
    """Returns (usable, token_still_present_after)."""
    store = InMemoryTokenStorage()
    ContextState.get().user_id.set(USER)
    if stored is not None:
        await store.store(USER, stored)

    async def _fake_resolve(builder, cfg, source_id):
        return store

    # _token_usable does `from .factory import _resolve_token_storage`, so patch it there.
    with patch("aiq_api.mcp_auth.factory._resolve_token_storage", _fake_resolve):
        usable = await runtime_tools._token_usable(builder=None, cfg=None, source_id="gdrive")
    still_there = (await store.retrieve(USER)) is not None
    return usable, still_there


def test_valid_token_is_usable_and_kept():
    usable, still_there = asyncio.run(_check(_auth(expired=False)))
    assert usable is True
    assert still_there is True


def test_expired_token_is_not_usable_and_invalidated():
    # The core fix: an expired token must be reported unusable AND deleted, so the
    # next get_status flips the card to Reconnect instead of false "connected".
    usable, still_there = asyncio.run(_check(_auth(expired=True)))
    assert usable is False
    assert still_there is False


def test_missing_token_is_not_usable():
    usable, still_there = asyncio.run(_check(None))
    assert usable is False
    assert still_there is False
