# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ``SandboxProvider`` base — the thin contract a sandbox backend must satisfy.

Design: force only the minimum (``_create_session`` + declared ``capabilities``).
Everything else — lazy creation, locking, idempotency-gated retry, and cleanup — is
shared here so a new provider implements just the SDK-specific parts. File tools
(``read_file``/``write_file``/``edit_file``/``ls``/``glob``) are inherited from
``BaseSandbox``, which builds them on top of ``execute``; providers never reimplement them.

This mirrors the knowledge-layer adapter philosophy: a small required surface, optional
capabilities with safe defaults, and provider-owned error classification.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING
from typing import TypeVar

from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.protocol import FileDownloadResponse
from deepagents.backends.protocol import FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

from .capabilities import SandboxCapabilities

if TYPE_CHECKING:
    from .config import SandboxConfig

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class SandboxProvider(BaseSandbox, ABC):
    """Job-scoped, lazily-created sandbox backend behind a uniform contract.

    Subclasses implement provider-specific session creation and declare their
    capabilities. The base provides shared resilience (single-flight creation,
    a serialization lock around remote calls, and idempotency-gated retry driven
    by the provider's own :meth:`is_recoverable_error`).

    Attributes:
        provider_name: Registry key for this provider.
    """

    provider_name: str = "base"

    def __init__(self, config: SandboxConfig, job_id: str) -> None:
        """Initialize the provider.

        Args:
            config: Resolved sandbox configuration for the job.
            job_id: Async job identifier used to scope the sandbox identity.
        """
        self.config = config
        self.job_id = job_id
        self.sandbox_name = self._scoped_name(job_id)
        self._session: BaseSandbox | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Required surface (the only things a provider must implement)
    # ------------------------------------------------------------------ #
    @abstractmethod
    def _create_session(self) -> BaseSandbox:
        """Create the underlying provider-specific ``BaseSandbox`` session.

        Implementations own the SDK calls (gateway connect, create/attach, image
        build, ready-wait). They must NOT silently attach to a sandbox owned by a
        prior job; collisions should produce a fresh, job-scoped sandbox.

        Returns:
            A concrete ``BaseSandbox`` (e.g. the langchain-modal / langchain-openshell adapter).
        """

    @property
    @abstractmethod
    def capabilities(self) -> SandboxCapabilities:
        """Return the security/lifecycle guarantees this provider can enforce."""

    # ------------------------------------------------------------------ #
    # Optional hooks with safe, conservative defaults (override to opt in)
    # ------------------------------------------------------------------ #
    @classmethod
    def _scoped_name(cls, job_id: str) -> str:
        """Translate a job id into a provider-legal, job-scoped sandbox name.

        Providers override to apply their own naming rules (length, charset).
        """
        return job_id

    def is_recoverable_error(self, exc: Exception) -> bool:
        """Classify an exception as a transient/stale-sandbox error worth retrying.

        Conservative default returns ``False`` so unknown providers never recreate
        and silently re-run against an empty sandbox. Providers override using their
        own SDK's typed exceptions rather than fragile string matching.
        """
        return False

    def close(self) -> None:
        """Release the underlying sandbox session, if any.

        Idempotent. Default delegates to the session's ``close`` when present;
        providers without remote cleanup can rely on this no-op-when-absent default.
        """
        with self._lock:
            session = self._session
            self._session = None
        if session is not None and hasattr(session, "close"):
            try:
                session.close()
            except Exception:  # noqa: BLE001 - cleanup must never raise on the terminal path
                logger.warning("Sandbox %s cleanup failed", self.sandbox_name, exc_info=True)

    def terminate(self) -> None:
        """Forcibly stop any running execution and release the sandbox.

        Default implementation falls back to :meth:`close`. Providers that can kill a
        running ``execute`` mid-flight should override and declare
        ``supports_terminate`` in their capabilities. Used on the cancellation path.
        """
        self.close()

    @property
    def id(self) -> str:
        """Stable identifier: the live session id once created, else the scoped name."""
        session = self._session
        return session.id if session is not None else self.sandbox_name

    # ------------------------------------------------------------------ #
    # Byte/exec surface — shared resilience, delegated to the session
    # ------------------------------------------------------------------ #
    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Run a command in the sandbox (non-idempotent; no recreate-and-retry).

        The per-call ``timeout`` is clamped to the configured sandbox lifetime
        (``config.timeout``). Agent-supplied timeouts are unreliable (e.g. a tool
        may pass milliseconds where the backend expects seconds), and a single
        ``execute`` should never outlive the sandbox or exceed a provider's hard
        cap, so we bound it rather than let the backend reject the call.
        """
        timeout = self._clamp_timeout(timeout)
        return self._call("execute", lambda s: s.execute(command, timeout=timeout), idempotent=False)

    def _clamp_timeout(self, timeout: int | None) -> int | None:
        """Bound a per-call timeout to ``config.timeout`` (the sandbox max lifetime)."""
        if timeout is None:
            return None
        ceiling = self.config.timeout
        if timeout > ceiling:
            logger.warning(
                "Sandbox %s execute timeout %ss exceeds configured limit %ss; clamping",
                self.sandbox_name,
                timeout,
                ceiling,
            )
            return ceiling
        return max(1, timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload input files into the sandbox (idempotent; safe to retry)."""
        return self._call("upload_files", lambda s: s.upload_files(files), idempotent=True)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from the sandbox for artifact harvesting (idempotent)."""
        return self._call("download_files", lambda s: s.download_files(paths), idempotent=True)

    # ------------------------------------------------------------------ #
    # Internal lifecycle
    # ------------------------------------------------------------------ #
    def _session_or_create(self) -> BaseSandbox:
        """Return the live session, creating it once under the lock (single-flight)."""
        with self._lock:
            if self._session is None:
                logger.info("Sandbox session init: provider=%s name=%s", self.provider_name, self.sandbox_name)
                self._session = self._create_session()
            return self._session

    def _reset_session(self) -> None:
        """Drop and recreate the session (used only for idempotent recoverable retries)."""
        with self._lock:
            logger.warning(
                "Sandbox session RESET: provider=%s name=%s (prior in-sandbox files are lost)",
                self.provider_name,
                self.sandbox_name,
            )
            self._session = self._create_session()

    def _call(self, op_name: str, fn: Callable[[BaseSandbox], _T], *, idempotent: bool) -> _T:
        """Run a remote call with the serialization lock and gated retry.

        The lock serializes calls into a single shared job sandbox to avoid
        filesystem races and reset-during-execute hazards. Retry only happens when
        the operation is idempotent AND the provider classifies the error as
        recoverable; otherwise the error propagates (fail-safe over fail-silent).
        """
        with self._lock:
            try:
                return fn(self._session_or_create())
            except Exception as exc:
                if idempotent and self.is_recoverable_error(exc):
                    logger.warning("Sandbox %s recoverable error on %s; recreating and retrying once", self.id, op_name)
                    self._reset_session()
                    return fn(self._session_or_create())
                raise
