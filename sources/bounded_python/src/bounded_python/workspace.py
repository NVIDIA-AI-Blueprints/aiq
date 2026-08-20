# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Process-isolated, JSON-state analytical workspaces."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class WorkspaceLimits:
    """Resource and payload limits for one workspace manager."""

    wall_timeout_seconds: float = 5.0
    cpu_time_seconds: int = 3
    memory_mb: int = 256
    max_code_chars: int = 20_000
    max_input_bytes: int = 1_000_000
    max_state_bytes: int = 2_000_000
    max_output_chars: int = 50_000
    workspace_ttl_seconds: int = 3_600
    max_workspaces: int = 128


@dataclass(slots=True)
class _Workspace:
    state: dict[str, Any] = field(default_factory=dict)
    touched_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _response(status: str, **payload: Any) -> str:
    return json.dumps({"status": status, **payload}, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class BoundedPythonWorkspace:
    """Own explicit, isolated workspaces and execute each call in a subprocess."""

    def __init__(self, limits: WorkspaceLimits | None = None) -> None:
        self.limits = limits or WorkspaceLimits()
        self._workspaces: dict[str, _Workspace] = {}
        self._manager_lock = asyncio.Lock()
        self._worker_path = Path(__file__).with_name("worker.py")

    async def run(
        self,
        *,
        operation: str,
        workspace_id: str | None = None,
        code: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """Dispatch one non-raising workspace operation."""

        try:
            if operation == "start":
                return await self._start()
            if not workspace_id:
                return _response("error", error="workspace_id_required")
            workspace = await self._get_workspace(workspace_id)
            if workspace is None:
                return _response("error", error="workspace_not_found_or_expired", workspace_id=workspace_id)
            if operation == "execute":
                return await self._execute(workspace_id, workspace, code=code, inputs=inputs)
            if operation == "inspect":
                return await self._inspect(workspace_id, workspace)
            if operation == "reset":
                return await self._reset(workspace_id, workspace)
            if operation == "close":
                return await self._close(workspace_id)
            return _response("error", error="unsupported_operation", operation=operation)
        except Exception as exc:  # noqa: BLE001 - tool boundary must never crash the agent
            return _response("error", error="workspace_failure", detail=type(exc).__name__)

    async def _start(self) -> str:
        async with self._manager_lock:
            self._remove_expired_locked()
            if len(self._workspaces) >= self.limits.max_workspaces:
                return _response("error", error="workspace_limit_reached")
            workspace_id = str(uuid4())
            self._workspaces[workspace_id] = _Workspace()
        return _response("ok", operation="start", workspace_id=workspace_id)

    async def _get_workspace(self, workspace_id: str) -> _Workspace | None:
        async with self._manager_lock:
            self._remove_expired_locked()
            workspace = self._workspaces.get(workspace_id)
            if workspace is not None:
                workspace.touched_at = time.monotonic()
            return workspace

    def _remove_expired_locked(self) -> None:
        cutoff = time.monotonic() - self.limits.workspace_ttl_seconds
        expired = [key for key, workspace in self._workspaces.items() if workspace.touched_at < cutoff]
        for key in expired:
            self._workspaces.pop(key, None)

    async def _inspect(self, workspace_id: str, workspace: _Workspace) -> str:
        async with workspace.lock:
            workspace.touched_at = time.monotonic()
            return _response("ok", operation="inspect", workspace_id=workspace_id, state=workspace.state)

    async def _reset(self, workspace_id: str, workspace: _Workspace) -> str:
        async with workspace.lock:
            workspace.state = {}
            workspace.touched_at = time.monotonic()
            return _response("ok", operation="reset", workspace_id=workspace_id)

    async def _close(self, workspace_id: str) -> str:
        async with self._manager_lock:
            removed = self._workspaces.pop(workspace_id, None)
        if removed is None:
            return _response("error", error="workspace_not_found_or_expired", workspace_id=workspace_id)
        return _response("ok", operation="close", workspace_id=workspace_id)

    async def _execute(
        self,
        workspace_id: str,
        workspace: _Workspace,
        *,
        code: str | None,
        inputs: dict[str, Any] | None,
    ) -> str:
        if not code or not code.strip():
            return _response("error", error="code_required", workspace_id=workspace_id)
        if len(code) > self.limits.max_code_chars:
            return _response("error", error="code_too_large", workspace_id=workspace_id)
        try:
            input_payload = inputs or {}
            if len(_json_bytes(input_payload)) > self.limits.max_input_bytes:
                return _response("error", error="inputs_too_large", workspace_id=workspace_id)
        except (TypeError, ValueError):
            return _response("error", error="inputs_must_be_finite_json", workspace_id=workspace_id)

        async with workspace.lock:
            payload = {"code": code, "inputs": input_payload, "state": workspace.state}
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-S",
                str(self._worker_path),
                str(self.limits.cpu_time_seconds),
                str(self.limits.memory_mb * 1024 * 1024),
                str(self.limits.max_output_chars),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
            )
            try:
                stdout, _stderr = await asyncio.wait_for(
                    process.communicate(_json_bytes(payload)),
                    timeout=self.limits.wall_timeout_seconds,
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return _response("error", error="execution_timed_out", workspace_id=workspace_id)

            if process.returncode != 0:
                return _response(
                    "error",
                    error="execution_process_failed",
                    workspace_id=workspace_id,
                    return_code=process.returncode,
                )
            try:
                result = json.loads(stdout)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return _response("error", error="invalid_worker_response", workspace_id=workspace_id)
            if result.get("status") != "ok":
                return _response(
                    "error",
                    error=result.get("error", "execution_failed"),
                    detail=result.get("detail"),
                    workspace_id=workspace_id,
                )
            try:
                if len(_json_bytes(result["state"])) > self.limits.max_state_bytes:
                    return _response("error", error="state_too_large", workspace_id=workspace_id)
            except (KeyError, TypeError, ValueError):
                return _response("error", error="invalid_worker_state", workspace_id=workspace_id)
            workspace.state = result["state"]
            workspace.touched_at = time.monotonic()
            return _response(
                "ok",
                operation="execute",
                workspace_id=workspace_id,
                result=result.get("result"),
                output=result.get("output", ""),
                state_variables=sorted(workspace.state),
            )
