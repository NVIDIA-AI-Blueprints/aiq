# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

ULTRA_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
LIGHTNING_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
BUILD_BASE_URL = "https://integrate.api.nvidia.com/v1"

CONFIG_GLOBS = (
    ".agents/skills/aiq-configure-workflow/assets/config-scaffold.yml",
    "configs/config_*.yml",
    "frontends/benchmarks/**/configs/*.yml",
)
CONFIG_PATHS = tuple(sorted(path for pattern in CONFIG_GLOBS for path in REPO_ROOT.glob(pattern)))
FRESHQA_CONFIG_PATHS = tuple(sorted(REPO_ROOT.glob("frontends/benchmarks/freshqa/configs/*.yml")))

DEPRECATED_REFERENCES = (
    "/".join(("nvidia", "nemotron-3-super-120b-a12b")),
    "/".join(("nvidia", "nemotron-3-nano-30b-a3b")),
    "/".join(("nvidia", "nemotron-mini-4b-instruct")),
    "/".join(("nvidia", "llama-nemotron-embed-vl-1b-v2")),
    "/".join(("nvidia", "nemotron-nano-12b-v2-vl")),
    "/".join(("openai", "gpt-oss-120b")),
    ".".join(("inference-api", "nvidia", "com")),
)
SCANNED_SUFFIXES = {
    ".baseline",
    ".example",
    ".ipynb",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "results",
}


def _load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _model_for_alias(config: dict, alias: str) -> str:
    return config["llms"][alias]["model_name"]


def _thinking_enabled(config: dict, alias: str) -> bool:
    return bool(config["llms"][alias].get("chat_template_kwargs", {}).get("enable_thinking", False))


def _registered_source_tools(config: dict) -> set[str]:
    functions = config.get("functions", {})
    registries = (
        function
        for function in functions.values()
        if isinstance(function, dict) and function.get("_type") == "data_source_registry"
    )
    return {
        tool for registry in registries for source in registry.get("sources", []) for tool in source.get("tools", [])
    }


@pytest.mark.parametrize("config_path", CONFIG_PATHS, ids=lambda path: str(path.relative_to(REPO_ROOT)))
def test_default_profiles_use_role_appropriate_models(config_path: Path):
    config = _load_config(config_path)
    functions = config.get("functions", {})
    is_frontier_profile = config_path.name == "config_frontier_models.yml"

    for function in functions.values():
        if not isinstance(function, dict):
            continue

        function_type = function.get("_type")
        if function_type == "intent_classifier":
            if is_frontier_profile:
                continue
            alias = function["llm"]
            assert alias == "nemotron_lightning_intent_llm"
            assert _model_for_alias(config, alias) == LIGHTNING_MODEL
            assert config["llms"][alias]["base_url"] == BUILD_BASE_URL
            assert config["llms"][alias]["api_key"] == "${NVIDIA_API_KEY}"
            assert config["llms"][alias]["temperature"] == 0.1
            assert config["llms"][alias]["top_p"] == 0.9
            assert config["llms"][alias]["max_tokens"] == 1024
            assert not config["llms"][alias]["parallel_tool_calls"]
            assert not _thinking_enabled(config, alias)
        elif function_type == "shallow_research_agent":
            if is_frontier_profile:
                continue
            alias = function["llm"]
            assert alias == "nemotron_lightning_agent_llm"
            assert _model_for_alias(config, alias) == LIGHTNING_MODEL
            assert config["llms"][alias]["base_url"] == BUILD_BASE_URL
            assert config["llms"][alias]["api_key"] == "${NVIDIA_API_KEY}"
            assert config["llms"][alias]["temperature"] == 0.2
            assert config["llms"][alias]["top_p"] == 0.7
            assert config["llms"][alias]["max_tokens"] == 8192
            assert not config["llms"][alias]["parallel_tool_calls"]
            assert _thinking_enabled(config, alias)
        elif not is_frontier_profile and function_type == "clarifier_agent":
            assert _model_for_alias(config, function["llm"]) == ULTRA_MODEL
        elif not is_frontier_profile and function_type == "deep_research_agent":
            assert function["writer_llm"] == "nemotron_ultra_writer_llm"
            for role in (
                "orchestrator_llm",
                "source_router_llm",
                "researcher_llm",
                "planner_llm",
                "writer_llm",
            ):
                assert _model_for_alias(config, function[role]) == ULTRA_MODEL


@pytest.mark.parametrize("config_path", FRESHQA_CONFIG_PATHS, ids=lambda path: path.name)
def test_freshqa_research_tools_are_registered_data_sources(config_path: Path):
    config = _load_config(config_path)
    source_tools = _registered_source_tools(config)

    for function in config.get("functions", {}).values():
        if isinstance(function, dict) and function.get("_type") in {
            "shallow_research_agent",
            "deep_research_agent",
        }:
            assert set(function.get("tools", [])) <= source_tools


def test_deprecated_model_and_endpoint_references_are_absent():
    violations: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES or IGNORED_PARTS.intersection(path.parts):
            continue

        text = path.read_text(encoding="utf-8")
        for reference in DEPRECATED_REFERENCES:
            if reference in text:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {reference}")

    assert not violations, "Deprecated references remain:\n" + "\n".join(violations)
