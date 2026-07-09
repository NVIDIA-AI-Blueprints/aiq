# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Package and module-boundary tests for the MCP component."""

from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from mcp.server import fastmcp

import aiq_mcp
import mcp


@pytest.mark.parametrize(
    "module_name",
    [
        "aiq_mcp.checkpoint_todos",
        "aiq_mcp.db_url",
        "aiq_mcp.jobs",
        "aiq_mcp.job_store",
        "aiq_mcp.server",
        "aiq_mcp.workflow_runner",
    ],
)
def test_public_module_imports(module_name: str) -> None:
    assert import_module(module_name).__name__ == module_name


def test_package_does_not_shadow_protocol_package() -> None:
    component_root = Path(__file__).resolve().parents[1]
    component_source_root = component_root / "src"

    assert aiq_mcp.__name__ == "aiq_mcp"
    assert mcp.__name__ == "mcp"
    assert Path(aiq_mcp.__file__).parent.name == "aiq_mcp"
    assert not (component_root / "__init__.py").exists()
    assert component_source_root not in Path(mcp.__file__).parents
    assert component_source_root not in Path(fastmcp.__file__).parents


def test_package_version_present() -> None:
    assert aiq_mcp.__version__ == "0.1.0"


def test_console_script_entry_point_resolves_to_public_server_main() -> None:
    entry_point = next(
        candidate for candidate in entry_points(group="console_scripts") if candidate.name == "aiq-mcp-server"
    )

    assert entry_point.value == "aiq_mcp.server:main"
    assert entry_point.load() is import_module("aiq_mcp.server").main


def test_component_runtime_surface_is_explicitly_allowlisted() -> None:
    component_root = Path(aiq_mcp.__file__).parents[2]
    source_root = component_root / "src" / "aiq_mcp"
    assert {path.name for path in source_root.glob("*.py")} == {
        "__init__.py",
        "checkpoint_todos.py",
        "db_url.py",
        "jobs.py",
        "job_store.py",
        "server.py",
        "workflow_runner.py",
    }
