# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OpenShell lifecycle for one request-scoped persistent Python kernel."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from typing import Protocol

logger = logging.getLogger(__name__)

_REFERENCE_PATTERN = re.compile(r"gsf_[1-9][0-9]*")
_REMOTE_EVIDENCE_DIR = "evidence"
_REMOTE_REQUEST_DIR = "requests"
_WORKER_FILENAME = "kernel_worker.py"
_CLIENT_FILENAME = "kernel_client.py"
_LAUNCHER_FILENAME = "kernel_launcher.py"


class _SandboxBackend(Protocol):
    """Small provider surface used by the stateful Python transport."""

    @property
    def id(self) -> str: ...

    def execute(self, command: str, *, timeout: int | None = None) -> Any: ...

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[Any]: ...


class _SandboxRuntime(Protocol):
    """Request-owned OpenShell runtime and its provider backend."""

    @property
    def sandbox_backend(self) -> _SandboxBackend: ...

    @property
    def workdir(self) -> str: ...

    def close(self) -> None: ...

    def terminate(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PythonSessionLimits:
    """Operational bounds applied to each cell and uploaded evidence set."""

    wall_timeout_seconds: float = 30.0
    max_code_chars: int = 50_000
    max_output_chars: int = 50_000
    max_evidence_bytes: int = 20_000_000
    max_memory_mb: int = 8_192
    max_cpu_seconds: int = 600
    max_processes: int = 256
    max_open_files: int = 256
    max_file_bytes: int = 100_000_000


class OpenShellPythonSession:
    """Keep one scientific Python namespace alive in an attested OpenShell sandbox."""

    def __init__(
        self,
        *,
        runtime: _SandboxRuntime,
        host_manifest_path: Path,
        host_evidence_root: Path,
        limits: PythonSessionLimits | None = None,
    ) -> None:
        self.runtime = runtime
        self.host_manifest_path = host_manifest_path
        self.host_evidence_root = host_evidence_root.resolve()
        self.limits = limits or PythonSessionLimits()
        self._backend = runtime.sandbox_backend
        self._remote_root = PurePosixPath(runtime.workdir)
        self._remote_evidence_dir = self._remote_root / _REMOTE_EVIDENCE_DIR
        self._remote_request_dir = self._remote_root / _REMOTE_REQUEST_DIR
        self._remote_manifest = self._remote_evidence_dir / "gsf-results.json"
        self._remote_worker = self._remote_root / _WORKER_FILENAME
        self._remote_client = self._remote_root / _CLIENT_FILENAME
        self._remote_launcher = self._remote_root / _LAUNCHER_FILENAME
        self._remote_socket = self._remote_root / "kernel.sock"
        self._remote_pid = self._remote_root / "kernel.pid"
        self._remote_log = self._remote_root / "kernel.log"
        self._worker_path = Path(__file__).with_name(_WORKER_FILENAME)
        self._client_path = Path(__file__).with_name(_CLIENT_FILENAME)
        self._launcher_path = Path(__file__).with_name(_LAUNCHER_FILENAME)
        self._lock = asyncio.Lock()
        self._closed = False
        self._started = False
        self._sandbox_identity: str | None = None
        self._uploaded_references: set[str] = set()
        self._request_sequence = 0

    async def execute(self, code: str) -> str:
        """Execute one bounded cell and return a non-raising JSON response."""

        if not code.strip():
            return _json_response({"status": "error", "error": "code_required"})
        if len(code) > self.limits.max_code_chars:
            return _json_response({"status": "error", "error": "code_too_large"})

        async with self._lock:
            if self._closed:
                return _json_response({"status": "error", "error": "sandbox_closed"})
            try:
                request_path = await self._prepare_request(code)
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._execute_client, request_path),
                    timeout=self.limits.wall_timeout_seconds + 10.0,
                )
            except asyncio.CancelledError:
                await self._terminate()
                raise
            except TimeoutError:
                await self._terminate()
                return _json_response({"status": "error", "error": "execution_timed_out"})
            except Exception as exc:  # noqa: BLE001 - provider failures are sanitized before reaching the model
                logger.warning("OpenShell Python execution failed (error_type=%s)", type(exc).__name__)
                await self._terminate()
                return _json_response({"status": "error", "error": "sandbox_execution_failed"})

            if result.exit_code in {124, 137}:
                await self._terminate()
                return _json_response({"status": "error", "error": "execution_timed_out"})
            if result.exit_code not in {None, 0}:
                await self._terminate()
                return _json_response({"status": "error", "error": "kernel_process_failed"})
            try:
                payload = json.loads(str(result.output).strip())
                if not isinstance(payload, dict):
                    raise TypeError("kernel response must be an object")
                return _json_response(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                await self._terminate()
                return _json_response({"status": "error", "error": "invalid_kernel_response"})

    async def _prepare_request(self, code: str) -> str:
        """Synchronize trusted runtime files and exact GSF evidence into OpenShell."""

        manifest, evidence_files, references = self._evidence_bundle()
        self._request_sequence += 1
        request_path = self._remote_request_dir / f"cell-{self._request_sequence}.json"
        request = _json_response({"operation": "execute", "code": code}).encode("utf-8")

        files: dict[str, bytes] = {
            str(self._remote_manifest): manifest,
            str(request_path): request,
        }
        if not self._started:
            files.update(self._static_runtime_files())
            files.update(evidence_files)
        else:
            for reference in references:
                if reference not in self._uploaded_references:
                    remote_path = str(self._remote_evidence_dir / f"{reference}.json")
                    files[remote_path] = evidence_files[remote_path]

        await asyncio.to_thread(self._upload, files)
        identity = str(self._backend.id)
        if self._sandbox_identity is not None and identity != self._sandbox_identity:
            self._started = False
            self._uploaded_references.clear()
            full_files = {
                **self._static_runtime_files(),
                **evidence_files,
                str(self._remote_manifest): manifest,
                str(request_path): request,
            }
            await asyncio.to_thread(self._upload, full_files)
            identity = str(self._backend.id)
        self._sandbox_identity = identity
        self._uploaded_references = set(references)

        if not self._started:
            await asyncio.to_thread(self._start_worker)
            self._started = True
        return str(request_path)

    def _static_runtime_files(self) -> dict[str, bytes]:
        """Return the version-matched trusted worker transport files."""

        return {
            str(self._remote_worker): self._worker_path.read_bytes(),
            str(self._remote_client): self._client_path.read_bytes(),
            str(self._remote_launcher): self._launcher_path.read_bytes(),
        }

    def _evidence_bundle(self) -> tuple[bytes, dict[str, bytes], list[str]]:
        """Build a sandbox-local manifest from bounded request-owned GSF receipts."""

        raw_manifest = json.loads(self.host_manifest_path.read_text(encoding="utf-8"))
        entries = raw_manifest.get("results") if isinstance(raw_manifest, dict) else None
        if not isinstance(entries, list):
            raise ValueError("invalid GSF evidence manifest")

        total_bytes = 0
        remote_entries: list[dict[str, Any]] = []
        evidence_files: dict[str, bytes] = {}
        references: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("invalid GSF evidence entry")
            reference = entry.get("ref")
            if not isinstance(reference, str) or _REFERENCE_PATTERN.fullmatch(reference) is None:
                raise ValueError("invalid GSF evidence reference")
            host_path = Path(str(entry.get("path") or "")).resolve()
            if not host_path.is_relative_to(self.host_evidence_root):
                raise ValueError("GSF evidence path escaped its request root")
            content = host_path.read_bytes()
            json.loads(content)
            total_bytes += len(content)
            if total_bytes > self.limits.max_evidence_bytes:
                raise ValueError("GSF evidence exceeds the configured upload limit")

            remote_path = self._remote_evidence_dir / f"{reference}.json"
            evidence_files[str(remote_path)] = content
            references.append(reference)
            remote_entries.append(
                {
                    "ref": reference,
                    "question": entry.get("question"),
                    "database_name": entry.get("database_name"),
                    "request_id": entry.get("request_id"),
                    "row_count": entry.get("row_count"),
                    "columns": entry.get("columns"),
                    "truncated": bool(entry.get("truncated", False)),
                    "path": str(remote_path),
                }
            )

        manifest = _json_response({"version": 1, "results": remote_entries}).encode("utf-8")
        if total_bytes + len(manifest) > self.limits.max_evidence_bytes:
            raise ValueError("GSF evidence manifest exceeds the configured upload limit")
        return manifest, evidence_files, references

    def _upload(self, files: dict[str, bytes]) -> None:
        responses = self._backend.upload_files(list(files.items()))
        if len(responses) != len(files) or any(getattr(response, "error", None) for response in responses):
            raise RuntimeError("OpenShell file upload failed")

    def _start_worker(self) -> None:
        command = shlex.join(
            [
                "python3",
                "-I",
                str(self._remote_launcher),
                str(self._remote_worker),
                str(self._remote_manifest),
                str(self.limits.max_output_chars),
                str(self._remote_socket),
                str(self._remote_pid),
                str(self._remote_log),
                str(self.limits.max_memory_mb),
                str(self.limits.max_cpu_seconds),
                str(self.limits.max_processes),
                str(self.limits.max_open_files),
                str(self.limits.max_file_bytes),
            ]
        )
        result = self._backend.execute(command, timeout=30)
        if result.exit_code not in {None, 0}:
            raise RuntimeError("OpenShell kernel startup failed")

    def _execute_client(self, request_path: str) -> Any:
        response_limit = (self.limits.max_output_chars * 2) + 25_000
        command = shlex.join(
            [
                "/usr/bin/timeout",
                "--signal=KILL",
                f"{self.limits.wall_timeout_seconds:.3f}s",
                "python3",
                "-I",
                str(self._remote_client),
                str(self._remote_socket),
                request_path,
                str(response_limit),
            ]
        )
        return self._backend.execute(command, timeout=math.ceil(self.limits.wall_timeout_seconds) + 5)

    async def _terminate(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.to_thread(self.runtime.terminate)
        except Exception as exc:  # noqa: BLE001 - cleanup cannot expose provider details
            logger.warning("OpenShell Python termination failed (error_type=%s)", type(exc).__name__)

    async def aclose(self) -> None:
        """Delete the request-owned OpenShell sandbox and its complete process tree."""

        async with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                await asyncio.to_thread(self.runtime.close)
            except Exception as exc:  # noqa: BLE001 - cleanup cannot replace the agent result
                logger.warning("OpenShell Python cleanup failed (error_type=%s)", type(exc).__name__)


def _json_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
