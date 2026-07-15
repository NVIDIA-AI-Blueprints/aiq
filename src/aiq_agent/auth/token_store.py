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

"""Server-side store for user refresh tokens (foundation for issue #215).

Long-running async jobs outlive the ID token captured at submission time. To
support server-side refresh, the server must hold the user's refresh token.
This module provides the storage abstraction only — a pluggable
:class:`TokenStore` interface plus a default SQL-backed implementation that
encrypts the refresh token at rest. Wiring it into the login callback and the
worker's ``get_auth_token()`` refresh-on-demand path is deliberately left to
follow-up changes, so this piece is purely additive and changes no existing
behavior.

The interface is intentionally minimal and pluggable so a sibling
``MCPTokenStore`` (issue #217) can reuse the same shape.
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime

from .token_cipher import _ENV_KEY
from .token_cipher import TokenCipher
from .token_cipher import load_token_encryption_key

logger = logging.getLogger(__name__)

_DEFAULT_DB_URL = "sqlite:///./data/jobs.db"
_TABLE_NAME = "auth_token_store"
_disabled_warned = False
_store_cache: dict[str, SqlTokenStore] = {}


@dataclass(frozen=True)
class StoredToken:
    """A persisted refresh-token record for one browser session.

    The ``refresh_token`` field holds plaintext in memory only; it is encrypted
    before it reaches the database and decrypted on read.
    """

    session_id: str
    user_sub: str
    refresh_token: str
    id_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    updated_at: datetime | None = None


class TokenStore(ABC):
    """Pluggable persistence for user refresh tokens keyed by session id."""

    @abstractmethod
    async def put(self, token: StoredToken) -> None:
        """Insert or update the record for ``token.session_id``."""

    @abstractmethod
    async def get(self, session_id: str) -> StoredToken | None:
        """Return the record for ``session_id``, or None if absent."""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Remove the record for ``session_id`` (no error if absent)."""


class SqlTokenStore(TokenStore):
    """Default TokenStore backed by the job-store database.

    Refresh tokens are encrypted with :class:`TokenCipher` (AAD-bound to the
    session id) before being written. Blocking DB calls run in a thread executor
    so the store is safe to use from the async server.
    """

    def __init__(self, db_url: str, cipher: TokenCipher | None = None):
        """Create the store, ensuring the backing table exists."""
        self._db_url = db_url
        self._cipher = cipher or TokenCipher()
        self._engine = None
        self._metadata, self._table = self._build_schema()
        self._ensure_table()

    # -- engine / schema -------------------------------------------------

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            connect_args = {"check_same_thread": False} if self._db_url.startswith("sqlite") else {}
            self._engine = create_engine(self._db_url, connect_args=connect_args, pool_pre_ping=True)
        return self._engine

    @staticmethod
    def _build_schema():
        """Define the token table once; reused by every op (no per-call reflection)."""
        from sqlalchemy import Column
        from sqlalchemy import DateTime
        from sqlalchemy import MetaData
        from sqlalchemy import String
        from sqlalchemy import Table
        from sqlalchemy import Text
        from sqlalchemy.sql import func

        metadata = MetaData()
        table = Table(
            _TABLE_NAME,
            metadata,
            Column("session_id", String(128), primary_key=True),
            Column("user_sub", String(256), nullable=False, index=True),
            Column("refresh_token_encrypted", Text, nullable=False),
            Column("id_token_expires_at", DateTime(timezone=True), nullable=True),
            Column("refresh_token_expires_at", DateTime(timezone=True), nullable=True),
            Column("updated_at", DateTime(timezone=True), server_default=func.now()),
        )
        return metadata, table

    def _ensure_table(self) -> None:
        from sqlalchemy import inspect

        engine = self._get_engine()
        if not inspect(engine).has_table(_TABLE_NAME):
            self._metadata.create_all(engine)
            logger.info("Created %s table", _TABLE_NAME)

    # -- sync DB ops (run in executor by the async methods) --------------

    def _put_sync(self, token: StoredToken) -> None:
        encrypted = self._cipher.encrypt(token.refresh_token, aad=token.session_id)
        engine = self._get_engine()
        table = self._table
        row = {
            "session_id": token.session_id,
            "user_sub": token.user_sub,
            "refresh_token_encrypted": encrypted,
            "id_token_expires_at": token.id_token_expires_at,
            "refresh_token_expires_at": token.refresh_token_expires_at,
            "updated_at": token.updated_at or datetime.now(UTC),
        }
        # Atomic upsert keyed by session_id: a single INSERT ... ON CONFLICT DO
        # UPDATE, so concurrent writers for the same session can't race a
        # delete-then-insert gap. The dialect only selects which insert()
        # construct exposes on_conflict_do_update; the statement is identical.
        if engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as _dialect_insert
        else:
            from sqlalchemy.dialects.sqlite import insert as _dialect_insert

        stmt = _dialect_insert(table).values(**row)
        update_cols = {c: stmt.excluded[c] for c in row if c != "session_id"}
        stmt = stmt.on_conflict_do_update(index_elements=[table.c.session_id], set_=update_cols)
        with engine.begin() as conn:
            conn.execute(stmt)

    def _get_sync(self, session_id: str) -> StoredToken | None:
        from sqlalchemy import select

        engine = self._get_engine()
        table = self._table
        with engine.connect() as conn:
            result = conn.execute(select(table).where(table.c.session_id == session_id)).mappings().first()
        if result is None:
            return None
        refresh_token = self._cipher.decrypt(result["refresh_token_encrypted"], aad=session_id)
        return StoredToken(
            session_id=result["session_id"],
            user_sub=result["user_sub"],
            refresh_token=refresh_token,
            id_token_expires_at=result["id_token_expires_at"],
            refresh_token_expires_at=result["refresh_token_expires_at"],
            updated_at=result["updated_at"],
        )

    def _delete_sync(self, session_id: str) -> None:
        from sqlalchemy import delete

        engine = self._get_engine()
        table = self._table
        with engine.begin() as conn:
            conn.execute(delete(table).where(table.c.session_id == session_id))

    # -- async interface -------------------------------------------------

    async def put(self, token: StoredToken) -> None:
        """Encrypt and persist ``token`` (insert or replace)."""
        await asyncio.get_running_loop().run_in_executor(None, self._put_sync, token)

    async def get(self, session_id: str) -> StoredToken | None:
        """Fetch and decrypt the record for ``session_id``."""
        return await asyncio.get_running_loop().run_in_executor(None, self._get_sync, session_id)

    async def delete(self, session_id: str) -> None:
        """Delete the record for ``session_id``."""
        await asyncio.get_running_loop().run_in_executor(None, self._delete_sync, session_id)


def get_token_store(db_url: str | None = None) -> TokenStore | None:
    """Return the default TokenStore, or None when the feature is not configured.

    Server-side token storage requires ``AIQ_TOKEN_ENCRYPTION_KEY`` so refresh
    tokens are never written in plaintext.

    - Key **unset**: the store is disabled (returns None) and callers fall back
      to the existing freeze-at-submission behavior — a graceful skip.
    - Key **set but invalid**: raises ``TokenEncryptionConfigError`` so a
      misconfigured deployment fails loudly instead of silently degrading to
      no-op storage.

    The resulting store is cached per resolved database URL so repeat calls
    reuse one engine.
    """
    global _disabled_warned
    if not os.environ.get(_ENV_KEY):
        if not _disabled_warned:
            logger.info(
                "Server-side token store disabled: %s is not set. "
                "Long-running jobs will continue to use the token captured at submission.",
                _ENV_KEY,
            )
            _disabled_warned = True
        return None
    # Key is present: validate it now so a bad value fails loudly here rather
    # than at first use (raises TokenEncryptionConfigError).
    load_token_encryption_key()
    resolved = db_url or os.environ.get("NAT_JOB_STORE_DB_URL", _DEFAULT_DB_URL)
    cached = _store_cache.get(resolved)
    if cached is None:
        cached = SqlTokenStore(resolved)
        _store_cache[resolved] = cached
    return cached


def reset_token_store_cache_for_tests() -> None:
    """Dispose cached stores and clear the cache (test helper)."""
    global _disabled_warned
    for store in _store_cache.values():
        if store._engine is not None:
            store._engine.dispose()
    _store_cache.clear()
    _disabled_warned = False
