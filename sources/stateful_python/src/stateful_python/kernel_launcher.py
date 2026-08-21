# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Start one detached persistent kernel inside an OpenShell sandbox."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _limited_worker_command(
    *,
    worker_path: str,
    manifest_path: str,
    max_output_chars: str,
    socket_path: str,
    max_memory_mb: int,
    max_cpu_seconds: int,
    max_processes: int,
    max_open_files: int,
    max_file_bytes: int,
) -> list[str]:
    """Build a prlimit command that applies hard limits before worker exec."""

    memory_bytes = max_memory_mb * 1024 * 1024
    return [
        "/usr/bin/prlimit",
        f"--as={memory_bytes}:{memory_bytes}",
        f"--cpu={max_cpu_seconds}:{max_cpu_seconds}",
        f"--nproc={max_processes}:{max_processes}",
        f"--nofile={max_open_files}:{max_open_files}",
        f"--fsize={max_file_bytes}:{max_file_bytes}",
        "--",
        sys.executable,
        "-I",
        "-u",
        worker_path,
        manifest_path,
        max_output_chars,
        "--socket",
        socket_path,
    ]


def main() -> None:
    (
        worker_path,
        manifest_path,
        max_output_chars,
        socket_path,
        pid_path,
        log_path,
        max_memory_mb,
        max_cpu_seconds,
        max_processes,
        max_open_files,
        max_file_bytes,
    ) = sys.argv[1:]
    socket_file = Path(socket_path)
    socket_file.unlink(missing_ok=True)
    environment = {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    worker_command = _limited_worker_command(
        worker_path=worker_path,
        manifest_path=manifest_path,
        max_output_chars=max_output_chars,
        socket_path=socket_path,
        max_memory_mb=int(max_memory_mb),
        max_cpu_seconds=int(max_cpu_seconds),
        max_processes=int(max_processes),
        max_open_files=int(max_open_files),
        max_file_bytes=int(max_file_bytes),
    )
    with Path(log_path).open("ab") as log_file:
        process = subprocess.Popen(
            worker_command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
            env=environment,
        )
    Path(pid_path).write_text(str(process.pid), encoding="ascii")
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if socket_file.is_socket():
            return
        if process.poll() is not None:
            raise RuntimeError("kernel exited before its socket became ready")
        time.sleep(0.05)
    process.kill()
    raise TimeoutError("kernel socket did not become ready")


if __name__ == "__main__":
    main()
