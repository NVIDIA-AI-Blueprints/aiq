# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.  # noqa: E501
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

"""Launch a local Dask cluster and the web server."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

_DASK_LOOPBACK_HOST = "127.0.0.1"


def _terminate_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _install_signal_handlers(
    scheduler_proc: subprocess.Popen[str],
    worker_proc: subprocess.Popen[str],
    web_proc: subprocess.Popen[str],
) -> None:
    def _handle_signal(_signum: int, _frame: object) -> None:
        print("Shutting down...", flush=True)
        _terminate_process(web_proc)
        _terminate_process(worker_proc)
        _terminate_process(scheduler_proc)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def _wait_for_scheduler(port: int) -> None:
    from distributed import Client

    print("Waiting for scheduler to start...", flush=True)
    for attempt in range(1, 31):
        try:
            Client(f"tcp://{_DASK_LOOPBACK_HOST}:{port}", timeout="2s").close()
            print("Scheduler ready.", flush=True)
            return
        except Exception as exc:
            if attempt == 30:
                raise RuntimeError("Scheduler failed to start") from exc
            time.sleep(1)


def _scheduler_args(port: int) -> list[str]:
    """Return the command for the network-namespace-local embedded scheduler.

    The embedded scheduler has no authentication boundary. Keep both its task
    submission port and dashboard on loopback; operators that need a shared
    scheduler must deploy and secure it separately.
    """
    return [
        "dask-scheduler",
        "--host",
        _DASK_LOOPBACK_HOST,
        "--port",
        str(port),
        "--dashboard-address",
        f"{_DASK_LOOPBACK_HOST}:8787",
    ]


def _worker_args(
    scheduler_port: int,
    nworkers: str,
    nthreads: str,
    *,
    memory_limit: str | None = None,
    lifetime: str | None = None,
    lifetime_restart: bool = True,
) -> list[str]:
    """Return the command for workers in the embedded cluster.

    A Dask worker exposes unauthenticated RPC and diagnostics listeners in
    addition to its scheduler connection. Bind every listener to loopback so
    the embedded cluster remains local to the container network namespace.
    """
    args = [
        "dask-worker",
        f"tcp://{_DASK_LOOPBACK_HOST}:{scheduler_port}",
        "--host",
        _DASK_LOOPBACK_HOST,
        "--dashboard-address",
        f"{_DASK_LOOPBACK_HOST}:0",
        "--nworkers",
        str(nworkers),
        "--nthreads",
        str(nthreads),
        "--no-dashboard",
    ]
    if memory_limit:
        args += ["--memory-limit", memory_limit]
    if lifetime:
        args += ["--lifetime", lifetime]
        if lifetime_restart:
            args += ["--lifetime-restart"]
    return args


def main() -> int:
    if len(sys.argv) > 1:
        os.execvp(sys.argv[1], sys.argv[1:])

    config_file = os.getenv(
        "CONFIG_FILE",
        "/app/configs/config_web_default_llamaindex.yml",
    )
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    scheduler_port = int(os.getenv("DASK_SCHEDULER_PORT", "8786"))
    nworkers = os.getenv("DASK_NWORKERS", "1")
    nthreads = os.getenv("DASK_NTHREADS", "4")
    memory_limit = os.getenv("DASK_MEMORY_LIMIT")
    lifetime = os.getenv("DASK_LIFETIME")

    print("============================================", flush=True)
    print("NVIDIA NeMo Agent toolkit - Local Dask Mode", flush=True)
    print("============================================", flush=True)
    print("", flush=True)
    print(f"Config: {config_file}", flush=True)
    print(f"API:    http://{host}:{port}", flush=True)
    print(f"Dask:   tcp://{_DASK_LOOPBACK_HOST}:{scheduler_port}", flush=True)
    print("", flush=True)

    scheduler_proc = subprocess.Popen(_scheduler_args(scheduler_port))

    try:
        _wait_for_scheduler(scheduler_port)
    except RuntimeError as exc:
        _terminate_process(scheduler_proc)
        raise SystemExit(str(exc)) from exc

    lifetime_restart = os.getenv("DASK_LIFETIME_RESTART", "true").lower() != "false"
    worker_proc = subprocess.Popen(
        _worker_args(
            scheduler_port,
            nworkers,
            nthreads,
            memory_limit=memory_limit,
            lifetime=lifetime,
            lifetime_restart=lifetime_restart,
        ),
    )

    print("Waiting for worker to connect...", flush=True)
    time.sleep(3)

    os.environ["NAT_DASK_SCHEDULER_ADDRESS"] = f"tcp://{_DASK_LOOPBACK_HOST}:{scheduler_port}"

    print("", flush=True)
    print("--------------------------------------------", flush=True)
    print("  Dask cluster ready", flush=True)
    print("  Starting web server...", flush=True)
    print("--------------------------------------------", flush=True)
    print("", flush=True)

    web_proc = subprocess.Popen(["python", "/app/deploy/start_web.py"])
    _install_signal_handlers(scheduler_proc, worker_proc, web_proc)

    try:
        return web_proc.wait()
    finally:
        _terminate_process(web_proc)
        _terminate_process(worker_proc)
        _terminate_process(scheduler_proc)


if __name__ == "__main__":
    sys.exit(main())
