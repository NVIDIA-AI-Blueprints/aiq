# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

ULTRA_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"

CONFIG_GLOBS = (
    ".agents/skills/aiq-configure-workflow/assets/config-scaffold.yml",
    "configs/config_*.yml",
    "frontends/benchmarks/**/configs/*.yml",
)
CONFIG_PATHS = tuple(sorted(path for pattern in CONFIG_GLOBS for path in REPO_ROOT.glob(pattern)))

# Super remains intentionally pinned for intent and shallow research until the
# separately gated Nano 3.5 follow-up is available. Every other deprecated
# reference must be removed by this migration.
REPLACED_REFERENCES = (
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


@pytest.mark.parametrize("config_path", CONFIG_PATHS, ids=lambda path: str(path.relative_to(REPO_ROOT)))
def test_default_profiles_use_role_appropriate_models(config_path: Path):
    config = _load_config(config_path)
    functions = config.get("functions", {})

    for function in functions.values():
        if not isinstance(function, dict):
            continue

        function_type = function.get("_type")
        if function_type == "intent_classifier":
            assert _model_for_alias(config, function["llm"]) == SUPER_MODEL
        elif function_type == "shallow_research_agent":
            assert _model_for_alias(config, function["llm"]) == SUPER_MODEL
        elif config_path.name != "config_frontier_models.yml" and function_type == "clarifier_agent":
            assert _model_for_alias(config, function["llm"]) == ULTRA_MODEL
        elif config_path.name != "config_frontier_models.yml" and function_type == "deep_research_agent":
            assert function["writer_llm"] == "nemotron_ultra_writer_llm"
            for role in (
                "orchestrator_llm",
                "source_router_llm",
                "researcher_llm",
                "planner_llm",
                "writer_llm",
            ):
                assert _model_for_alias(config, function[role]) == ULTRA_MODEL


def test_replaced_model_and_endpoint_references_are_absent():
    violations: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES or IGNORED_PARTS.intersection(path.parts):
            continue

        text = path.read_text(encoding="utf-8")
        for reference in REPLACED_REFERENCES:
            if reference in text:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {reference}")

    assert not violations, "Replaced references remain:\n" + "\n".join(violations)
