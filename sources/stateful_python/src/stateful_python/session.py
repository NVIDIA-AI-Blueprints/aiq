# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Async lifecycle for one persistent Python kernel subprocess."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PythonSessionLimits:
    """Operational bounds applied to each cell in a persistent request kernel."""

    wall_timeout_seconds: float = 30.0
    max_code_chars: int = 50_000
    max_output_chars: int = 50_000


class PersistentPythonSession:
    """Keep Python globals alive in one subprocess for a single request."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        working_directory: Path,
        limits: PythonSessionLimits | None = None,
    ) -> None:
        self.manifest_path = manifest_path
        self.working_directory = working_directory
        self.limits = limits or PythonSessionLimits()
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._worker_path = Path(__file__).with_name("kernel_worker.py")

    async def _start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUNBUFFERED"] = "1"
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-u",
            str(self._worker_path),
            str(self.manifest_path),
            str(self.limits.max_output_chars),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.working_directory),
            env=environment,
        )

    async def execute(self, code: str) -> str:
        """Execute one cell and return a non-raising JSON response."""

        if not code.strip():
            return json.dumps({"status": "error", "error": "code_required"})
        if len(code) > self.limits.max_code_chars:
            return json.dumps({"status": "error", "error": "code_too_large"})
        async with self._lock:
            await self._start()
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                return json.dumps({"status": "error", "error": "kernel_start_failed"})
            payload = json.dumps({"operation": "execute", "code": code}, ensure_ascii=False) + "\n"
            try:
                process.stdin.write(payload.encode("utf-8"))
                await process.stdin.drain()
                raw_response = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=self.limits.wall_timeout_seconds,
                )
            except TimeoutError:
                await self._terminate()
                return json.dumps(
                    {
                        "status": "error",
                        "error": "execution_timed_out",
                        "detail": "The persistent kernel was restarted and its Python variables were lost.",
                    }
                )
            except (BrokenPipeError, ConnectionResetError):
                detail = await self._stderr_tail()
                await self._terminate()
                return json.dumps({"status": "error", "error": "kernel_process_failed", "detail": detail})
            if not raw_response:
                detail = await self._stderr_tail()
                await self._terminate()
                return json.dumps({"status": "error", "error": "kernel_process_failed", "detail": detail})
            try:
                return json.dumps(json.loads(raw_response), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                await self._terminate()
                return json.dumps({"status": "error", "error": "invalid_kernel_response"})

    async def _stderr_tail(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        try:
            value = await asyncio.wait_for(process.stderr.read(), timeout=0.25)
        except TimeoutError:
            return ""
        return value.decode("utf-8", errors="replace")[-2_000:]

    async def _terminate(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.kill()
        await process.wait()

    async def aclose(self) -> None:
        """Close the kernel process and release its pipes."""

        async with self._lock:
            process = self._process
            self._process = None
            if process is None or process.returncode is not None:
                return
            if process.stdin is not None:
                try:
                    process.stdin.write(b'{"operation":"close"}\n')
                    await process.stdin.drain()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                    return
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
            process.kill()
            await process.wait()
