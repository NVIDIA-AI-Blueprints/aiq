# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Phase 4 public configuration and packaging contract tests."""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import Requirement

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "configs" / "config_mcp.yml"
_MCP_MANIFEST_PATH = _REPO_ROOT / "mcp" / "pyproject.toml"
_ROOT_MANIFEST_PATH = _REPO_ROOT / "pyproject.toml"
_LOCK_PATH = _REPO_ROOT / "uv.lock"


def _iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_strings(nested)


def test_public_mcp_config_preserves_reference_orchestration_choices() -> None:
    config = yaml.safe_load(_CONFIG_PATH.read_text())

    assert set(config) == {"functions", "general", "llms", "workflow"}
    assert "front_end" not in config["general"]
    assert config.get("authentication") is None
    assert config.get("function_groups") is None
    assert config.get("object_stores") is None

    workflow = config["workflow"]
    assert workflow == {
        "_type": "chat_deepresearcher_agent",
        "enable_clarifier": False,
        "enable_escalation": True,
        "use_async_deep_research": False,
        "checkpoint_db": "${AIQ_CHECKPOINT_DB}",
    }

    functions = config["functions"]
    assert set(functions) == {
        "advanced_web_search_tool",
        "clarifier_agent",
        "data_sources",
        "deep_research_agent",
        "intent_classifier",
        "shallow_research_agent",
        "web_search_tool",
    }
    assert functions["intent_classifier"]["_type"] == "intent_classifier"
    assert functions["clarifier_agent"] == {
        "_type": "clarifier_agent",
        "llm": "nemotron_super_llm",
        "max_turns": 3,
        "log_response_max_chars": 2000,
        "verbose": True,
    }
    assert functions["shallow_research_agent"]["exclude_tools"] == ["advanced_web_search_tool"]
    assert functions["deep_research_agent"]["exclude_tools"] == ["web_search_tool"]

    sources = functions["data_sources"]["sources"]
    assert sources == [
        {
            "id": "web_search",
            "name": "Web Search",
            "description": "Search the public web for current information.",
            "tools": ["web_search_tool", "advanced_web_search_tool"],
        }
    ]


def test_public_mcp_config_uses_only_public_models_sources_and_environment_names() -> None:
    config = yaml.safe_load(_CONFIG_PATH.read_text())
    text = _CONFIG_PATH.read_text().lower()

    assert {entry["_type"] for entry in config["llms"].values()} == {"nim"}
    assert {entry["base_url"] for entry in config["llms"].values()} == {"https://integrate.api.nvidia.com/v1"}
    assert config["functions"]["web_search_tool"]["_type"] == "tavily_web_search"
    assert config["functions"]["advanced_web_search_tool"]["_type"] == "tavily_web_search"
    assert "nvidia_api_key" in text
    assert "tavily_api_key" in text
    assert {value for value in _iter_strings(config) if "://" in value} == {"https://integrate.api.nvidia.com/v1"}


def test_mcp_manifest_declares_public_direct_runtime_dependencies() -> None:
    manifest = tomllib.loads(_MCP_MANIFEST_PATH.read_text())
    dependency_names = {Requirement(value).name for value in manifest["project"]["dependencies"]}

    assert dependency_names == {
        "aiq-agent",
        "asyncpg",
        "langchain-core",
        "mcp",
        "msgpack",
        "nvidia-nat-core",
        "python-dotenv",
        "starlette",
        "tavily-web-search",
        "uvicorn",
    }
    assert manifest["project"]["name"] == "aiq-mcp-server"
    assert manifest["project"]["license"] == "Apache-2.0"
    assert manifest["project"]["license-files"] == ["LICENSE"]
    assert manifest["project"]["scripts"] == {"aiq-mcp-server": "aiq_mcp.server:main"}


def test_root_workspace_owns_mcp_package_and_single_lockfile() -> None:
    manifest = tomllib.loads(_ROOT_MANIFEST_PATH.read_text())

    assert "mcp" in manifest["tool"]["uv"]["workspace"]["members"]
    assert manifest["tool"]["uv"]["sources"]["aiq-mcp-server"] == {"workspace": True}
    assert manifest["tool"]["uv"]["sources"]["tavily-web-search"] == {"workspace": True}
    assert not (_REPO_ROOT / "mcp" / "uv.lock").exists()

    lock = tomllib.loads(_LOCK_PATH.read_text())
    assert any(package["name"] == "aiq-mcp-server" for package in lock["package"])
    for package in lock["package"]:
        source = package["source"]
        assert len(source) == 1
        if "registry" in source:
            assert source == {"registry": "https://pypi.org/simple"}
            continue
        editable = source.get("editable")
        assert isinstance(editable, str)
        assert not Path(editable).is_absolute()
        assert ".." not in Path(editable).parts
