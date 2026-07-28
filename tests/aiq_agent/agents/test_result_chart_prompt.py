# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
"""Guards the result-chart contract embedded in the researcher/writer prompts.

The shallow researcher and deep-research writer both instruct the agent to emit
declarative ``chart`` specs that the UI's ResultChart renderer parses. These
tests ensure the worked examples in those prompts stay valid JSON that matches
the renderer's schema, so the documented contract cannot silently drift.
"""

import json
import re
from pathlib import Path

import pytest

from aiq_agent.common import render_prompt_template

_AGENTS = Path(__file__).resolve().parents[3] / "src" / "aiq_agent" / "agents"
_PROMPTS = {
    "shallow": _AGENTS / "shallow_researcher" / "prompts" / "researcher.j2",
    "writer": _AGENTS / "deep_researcher" / "prompts" / "writer.j2",
}

# Kept in lockstep with CHART_TYPES in the UI's ResultChart/types.ts.
_CHART_TYPES = {"bar", "hbar", "line", "area", "grouped-bar", "delta"}
_CHART_BLOCK = re.compile(r"```chart\n(.*?)\n```", re.DOTALL)
_CAROUSEL_BLOCK = re.compile(r"```chart-carousel\n(.*?)\n```", re.DOTALL)


def _chart_examples(prompt_key: str) -> list[dict]:
    text = _PROMPTS[prompt_key].read_text()
    return [json.loads(block) for block in _CHART_BLOCK.findall(text)]


@pytest.mark.parametrize("prompt_key", list(_PROMPTS))
def test_prompt_defines_the_chart_contract(prompt_key: str) -> None:
    text = _PROMPTS[prompt_key].read_text()
    assert "## Presenting Data (Charts)" in text
    assert "chart-carousel" in text
    for chart_type in _CHART_TYPES:
        assert chart_type in text, f"{prompt_key} prompt omits chart type {chart_type!r}"


@pytest.mark.parametrize("prompt_key", list(_PROMPTS))
def test_prompt_carousel_examples_match_the_schema(prompt_key: str) -> None:
    text = _PROMPTS[prompt_key].read_text()
    blocks = _CAROUSEL_BLOCK.findall(text)
    assert blocks, f"{prompt_key} prompt has no ```chart-carousel example"
    for block in blocks:
        carousel = json.loads(block)
        assert carousel["title"]
        assert len(carousel["charts"]) >= 2
        for chart in carousel["charts"]:
            assert chart["type"] == "line"
            assert chart["title"], f"{prompt_key} carousel child is missing a non-empty title"
            assert chart["x"]["key"]
            assert chart["series"] and all(s["key"] for s in chart["series"])
            assert chart["data"] and all(isinstance(row, dict) for row in chart["data"])


@pytest.mark.parametrize("prompt_key", list(_PROMPTS))
def test_prompt_chart_examples_match_the_schema(prompt_key: str) -> None:
    examples = _chart_examples(prompt_key)
    assert examples, f"{prompt_key} prompt has no ```chart example"

    saw_full_chart = False
    saw_kpi_only = False
    for spec in examples:
        assert isinstance(spec, dict)
        assert spec["title"]
        if "type" in spec:
            saw_full_chart = True
            assert spec["type"] in _CHART_TYPES
            assert spec["x"]["key"]
            assert spec["series"] and all(s["key"] for s in spec["series"])
            assert spec["data"] and all(isinstance(row, dict) for row in spec["data"])
        else:
            saw_kpi_only = True
            assert spec["kpis"] and all(k["label"] and k["value"] for k in spec["kpis"])

    assert saw_full_chart, f"{prompt_key} prompt should show a full chart example"
    assert saw_kpi_only, f"{prompt_key} prompt should show a KPI-only example"


_WRITER_RENDER_CONTEXT = {
    "current_datetime": "2026-01-01T00:00:00Z",
    "user_info": None,
    "parent_report_context_available": False,
    "sandbox_workdir": "/sandbox/workdir",
    "sandbox_artifact_dir": "/sandbox/artifacts",
}


def _render_writer(*, execution_enabled: bool) -> str:
    return render_prompt_template(
        _PROMPTS["writer"].read_text(),
        execution_enabled=execution_enabled,
        **_WRITER_RENDER_CONTEXT,
    )


def test_writer_gates_inline_charts_to_the_non_sandbox_path() -> None:
    with_sandbox = _render_writer(execution_enabled=True)
    assert "## Figures" in with_sandbox
    assert "## Presenting Data" not in with_sandbox
    assert "```chart" not in with_sandbox

    without_sandbox = _render_writer(execution_enabled=False)
    assert "## Presenting Data (Charts)" in without_sandbox
    assert "```chart" in without_sandbox
    assert "## Figures" not in without_sandbox
