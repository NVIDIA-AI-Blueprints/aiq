# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Security invariants for the embedded Dask deployment entrypoint."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from distributed import Client
from distributed import LocalCluster


def _load_entrypoint():
    path = Path(__file__).parents[2] / "deploy" / "entrypoint.py"
    spec = importlib.util.spec_from_file_location("aiq_deploy_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedded_dask_scheduler_is_loopback_only() -> None:
    entrypoint = _load_entrypoint()

    command = entrypoint._scheduler_args(8786)

    assert entrypoint._DASK_LOOPBACK_HOST == "127.0.0.1"
    assert command[command.index("--host") + 1] == entrypoint._DASK_LOOPBACK_HOST
    assert command[command.index("--dashboard-address") + 1] == f"{entrypoint._DASK_LOOPBACK_HOST}:8787"
    assert command[command.index("--port") + 1] == "8786"


def test_embedded_dask_worker_is_loopback_only_and_preserves_limits() -> None:
    entrypoint = _load_entrypoint()

    command = entrypoint._worker_args(
        8786,
        "2",
        "3",
        memory_limit="800MB",
        lifetime="3600s",
        lifetime_restart=True,
    )

    assert command[1] == f"tcp://{entrypoint._DASK_LOOPBACK_HOST}:8786"
    assert command[command.index("--host") + 1] == entrypoint._DASK_LOOPBACK_HOST
    assert command[command.index("--dashboard-address") + 1] == f"{entrypoint._DASK_LOOPBACK_HOST}:0"
    assert command[command.index("--nworkers") + 1] == "2"
    assert command[command.index("--nthreads") + 1] == "3"
    assert command[command.index("--memory-limit") + 1] == "800MB"
    assert command[command.index("--lifetime") + 1] == "3600s"
    assert "--lifetime-restart" in command
    assert "--no-dashboard" in command


def test_embedded_dask_worker_can_disable_lifetime_restart() -> None:
    entrypoint = _load_entrypoint()

    command = entrypoint._worker_args(
        8786,
        "1",
        "4",
        lifetime="3600s",
        lifetime_restart=False,
    )

    assert "--lifetime" in command
    assert "--lifetime-restart" not in command
    assert "--memory-limit" not in command


def test_embedded_dask_worker_advertises_only_loopback() -> None:
    entrypoint = _load_entrypoint()
    worker_proc: subprocess.Popen[str] | None = None

    with (
        LocalCluster(
            n_workers=0,
            host=entrypoint._DASK_LOOPBACK_HOST,
            protocol="tcp",
            dashboard_address=None,
        ) as cluster,
        Client(cluster) as client,
    ):
        scheduler_port = cluster.scheduler_address.rsplit(":", maxsplit=1)[1]
        worker_proc = subprocess.Popen(
            entrypoint._worker_args(int(scheduler_port), "1", "1"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            client.wait_for_workers(1, timeout="20s")
            workers = client.scheduler_info()["workers"]
            assert len(workers) == 1
            worker_address, worker_info = next(iter(workers.items()))
            assert worker_address.startswith(f"tcp://{entrypoint._DASK_LOOPBACK_HOST}:")
            assert worker_info["host"] == entrypoint._DASK_LOOPBACK_HOST
            assert worker_info["nanny"].startswith(f"tcp://{entrypoint._DASK_LOOPBACK_HOST}:")
        finally:
            entrypoint._terminate_process(worker_proc)
