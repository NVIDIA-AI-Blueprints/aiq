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

"""Summary store for document summaries using SQLAlchemy.

Provides configurable SQLite/PostgreSQL storage for document summaries,
following the same pattern as EventStore in the jobs system.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from .schema import AvailableDocument

logger = logging.getLogger(__name__)

ENGINE_CACHE_TTL_SECONDS = 3600
ENGINE_CACHE_MAX_SIZE = 10


def _normalize_db_url(db_url: str, async_mode: bool = True) -> str:
    """Normalize database URL to use consistent drivers."""
    if db_url.startswith("postgresql") or db_url.startswith("postgres"):
        base_url = db_url.replace("+asyncpg", "").replace("+psycopg2", "").replace("+psycopg", "")
        if not base_url.startswith("postgresql://"):
            base_url = base_url.replace("postgres://", "postgresql://")
        return (
            f"{base_url.replace('postgresql://', 'postgresql+psycopg://')}"
            if async_mode
            else base_url.replace("postgresql://", "postgresql+psycopg://")
        )
    elif db_url.startswith("sqlite"):
        base_url = db_url.replace("+aiosqlite", "")
        return base_url.replace("sqlite:///", "sqlite+aiosqlite:///") if async_mode else base_url
    return db_url


class SummaryStore:
    """SQLAlchemy-based store for document summaries.

    Features:
    - Automatic SQLite/PostgreSQL support based on db_url
    - Connection pooling with TTL-based cache management
    - Both sync and async operations supported
    """

    _async_engine_cache: dict[str, tuple[Any, float]] = {}
    _sync_engine_cache: dict[str, tuple[Any, float]] = {}
    _cache_lock = threading.Lock()
    _tables_initialized: set[str] = set()

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._sync_engine = self._get_or_create_sync_engine(db_url)
        self._ensure_table_sync()
        logger.info("SummaryStore initialized: %s", db_url[:50])

    @classmethod
    def _get_or_create_sync_engine(cls, db_url: str):
        """Get or create a sync SQLAlchemy engine with TTL-based caching."""
        with cls._cache_lock:
            cls._cleanup_stale_engines(cls._sync_engine_cache)

            if db_url in cls._sync_engine_cache:
                engine, _ = cls._sync_engine_cache[db_url]
                cls._sync_engine_cache[db_url] = (engine, time.monotonic())
                return engine

            from sqlalchemy import create_engine

            normalized_url = _normalize_db_url(db_url, async_mode=False)
            is_sqlite = normalized_url.startswith("sqlite")
            connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}

            engine = create_engine(
                normalized_url,
                pool_pre_ping=True,
                pool_size=1 if is_sqlite else 5,
                max_overflow=0 if is_sqlite else 10,
                connect_args=connect_args,
            )
            cls._sync_engine_cache[db_url] = (engine, time.monotonic())
            logger.debug("Created sync engine for %s", db_url[:50])
            return engine

    @classmethod
    def _get_or_create_async_engine(cls, db_url: str):
        """Get or create an async SQLAlchemy engine with TTL-based caching."""
        with cls._cache_lock:
            cls._cleanup_stale_engines(cls._async_engine_cache)

            if db_url in cls._async_engine_cache:
                engine, _ = cls._async_engine_cache[db_url]
                cls._async_engine_cache[db_url] = (engine, time.monotonic())
                return engine

            from sqlalchemy.ext.asyncio import create_async_engine

            normalized_url = _normalize_db_url(db_url, async_mode=True)
            is_sqlite = normalized_url.startswith("sqlite")

            engine = create_async_engine(
                normalized_url,
                pool_pre_ping=True,
                pool_size=1 if is_sqlite else 5,
                max_overflow=0 if is_sqlite else 10,
            )
            cls._async_engine_cache[db_url] = (engine, time.monotonic())
            logger.debug("Created async engine for %s", db_url[:50])
            return engine

    @classmethod
    def _cleanup_stale_engines(cls, cache: dict[str, tuple[Any, float]]):
        """Remove engines that haven't been used recently."""
        now = time.monotonic()
        stale_keys = [key for key, (_, last_used) in cache.items() if now - last_used > ENGINE_CACHE_TTL_SECONDS]
        for key in stale_keys:
            engine, _ = cache.pop(key, (None, 0))
            if engine:
                try:
                    engine.dispose()
                    logger.debug("Disposed stale engine for %s", key[:50])
                except Exception as e:
                    logger.warning("Failed to dispose engine: %s", e)

        if len(cache) > ENGINE_CACHE_MAX_SIZE:
            sorted_entries = sorted(cache.items(), key=lambda x: x[1][1])
            for key, (engine, _) in sorted_entries[: len(sorted_entries) - ENGINE_CACHE_MAX_SIZE]:
                cache.pop(key, None)
                if engine:
                    try:
                        engine.dispose()
                    except (RuntimeError, OSError):
                        pass

    def _ensure_table_sync(self):
        """Create summaries table if it doesn't exist (sync)."""
        with SummaryStore._cache_lock:
            if self.db_url in SummaryStore._tables_initialized:
                return

            from sqlalchemy import Column
            from sqlalchemy import DateTime
            from sqlalchemy import Index
            from sqlalchemy import MetaData
            from sqlalchemy import PrimaryKeyConstraint
            from sqlalchemy import String
            from sqlalchemy import Table
            from sqlalchemy import Text
            from sqlalchemy import inspect
            from sqlalchemy.sql import func

            inspector = inspect(self._sync_engine)
            if not inspector.has_table("summaries"):
                metadata = MetaData()
                Table(
                    "summaries",
                    metadata,
                    Column("collection", String(256), nullable=False),
                    Column("filename", String(512), nullable=False),
                    Column("summary", Text, nullable=False),
                    Column("created_at", DateTime, server_default=func.now()),
                    PrimaryKeyConstraint("collection", "filename"),
                    Index("idx_summaries_collection", "collection"),
                )
                metadata.create_all(self._sync_engine)
                logger.info("Created summaries table in %s", self.db_url[:50])

            SummaryStore._tables_initialized.add(self.db_url)

    @classmethod
    async def _ensure_table_async(cls, db_url: str):
        """Ensure summaries table exists (async)."""
        if db_url in cls._tables_initialized:
            return

        from sqlalchemy import Column
        from sqlalchemy import DateTime
        from sqlalchemy import Index
        from sqlalchemy import MetaData
        from sqlalchemy import PrimaryKeyConstraint
        from sqlalchemy import String
        from sqlalchemy import Table
        from sqlalchemy import Text
        from sqlalchemy.sql import func

        engine = cls._get_or_create_async_engine(db_url)
        metadata = MetaData()

        Table(
            "summaries",
            metadata,
            Column("collection", String(256), nullable=False),
            Column("filename", String(512), nullable=False),
            Column("summary", Text, nullable=False),
            Column("created_at", DateTime, server_default=func.now()),
            PrimaryKeyConstraint("collection", "filename"),
            Index("idx_summaries_collection", "collection"),
        )

        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: metadata.create_all(sync_conn))

        cls._tables_initialized.add(db_url)
        logger.info("Created summaries table (async) in %s", db_url[:50])

    def register(self, collection: str, filename: str, summary: str) -> None:
        """Store a document summary (sync)."""
        from sqlalchemy import text

        # Use upsert pattern that works for both SQLite and PostgreSQL
        is_postgres = self.db_url.startswith("postgres")

        try:
            with self._sync_engine.connect() as conn:
                if is_postgres:
                    conn.execute(
                        text(
                            "INSERT INTO summaries (collection, filename, summary) "
                            "VALUES (:collection, :filename, :summary) "
                            "ON CONFLICT (collection, filename) DO UPDATE SET summary = EXCLUDED.summary"
                        ),
                        {"collection": collection, "filename": filename, "summary": summary},
                    )
                else:
                    # SQLite uses INSERT OR REPLACE
                    conn.execute(
                        text(
                            "INSERT OR REPLACE INTO summaries (collection, filename, summary) "
                            "VALUES (:collection, :filename, :summary)"
                        ),
                        {"collection": collection, "filename": filename, "summary": summary},
                    )
                conn.commit()
                logger.debug("Registered summary for %s in %s", filename, collection)
        except Exception as e:
            logger.warning("Failed to register summary for %s: %s", filename, e)

    def get_all(self, collection: str) -> list[AvailableDocument]:
        """Get all documents with summaries for a collection (sync)."""
        from sqlalchemy import text

        from .schema import AvailableDocument

        try:
            with self._sync_engine.connect() as conn:
                result = conn.execute(
                    text("SELECT filename, summary FROM summaries WHERE collection = :collection"),
                    {"collection": collection},
                )
                return [AvailableDocument(file_name=row[0], summary=row[1]) for row in result]
        except Exception as e:
            logger.warning("Failed to get summaries for %s: %s", collection, e)
            return []

    async def get_all_async(self, collection: str) -> list[AvailableDocument]:
        """Get all documents with summaries for a collection (async)."""
        from sqlalchemy import text

        from .schema import AvailableDocument

        try:
            await self._ensure_table_async(self.db_url)
            engine = self._get_or_create_async_engine(self.db_url)
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT filename, summary FROM summaries WHERE collection = :collection"),
                    {"collection": collection},
                )
                return [AvailableDocument(file_name=row[0], summary=row[1]) for row in result]
        except Exception as e:
            logger.warning("Failed to get summaries async for %s: %s", collection, e)
            # Fallback to sync
            return self.get_all(collection)

    def unregister(self, collection: str, filename: str) -> None:
        """Remove a document's summary (sync)."""
        from sqlalchemy import text

        try:
            with self._sync_engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM summaries WHERE collection = :collection AND filename = :filename"),
                    {"collection": collection, "filename": filename},
                )
                conn.commit()
                logger.debug("Unregistered summary for %s in %s", filename, collection)
        except Exception as e:
            logger.warning("Failed to unregister summary for %s: %s", filename, e)

    def clear_collection(self, collection: str) -> None:
        """Remove all summaries for a collection (sync)."""
        from sqlalchemy import text

        try:
            with self._sync_engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM summaries WHERE collection = :collection"),
                    {"collection": collection},
                )
                conn.commit()
                logger.debug("Cleared summaries for collection %s", collection)
        except Exception as e:
            logger.warning("Failed to clear summaries for %s: %s", collection, e)

    def clear_all(self) -> None:
        """Remove all summaries (sync)."""
        from sqlalchemy import text

        try:
            with self._sync_engine.connect() as conn:
                conn.execute(text("DELETE FROM summaries"))
                conn.commit()
                logger.debug("Cleared all summaries")
        except Exception as e:
            logger.warning("Failed to clear all summaries: %s", e)

    @classmethod
    def dispose_all_engines(cls):
        """Dispose all cached engines (for shutdown)."""
        import asyncio

        with cls._cache_lock:
            for key, (engine, _) in list(cls._sync_engine_cache.items()):
                try:
                    engine.dispose()
                except (RuntimeError, OSError):
                    pass
            cls._sync_engine_cache.clear()

            for key, (engine, _) in list(cls._async_engine_cache.items()):
                try:
                    coro = engine.dispose()
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(coro)
                    except RuntimeError:
                        asyncio.run(coro)
                except (RuntimeError, OSError):
                    pass
            cls._async_engine_cache.clear()

            cls._tables_initialized.clear()
