# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Tests for NAT trace parsing and phase inference.

Module under test: src/aiq_agent/tokenomics/nat_adapter.py
"""

import json
from pathlib import Path

import pytest

from aiq_agent.tokenomics.nat_adapter import _build_task_windows
from aiq_agent.tokenomics.nat_adapter import _extract_subagent_type
from aiq_agent.tokenomics.nat_adapter import _infer_phase
from aiq_agent.tokenomics.nat_adapter import _TaskWindow
from aiq_agent.tokenomics.nat_adapter import parse_trace
from aiq_agent.tokenomics.pricing import PricingRegistry
from aiq_agent.tokenomics.profile import PHASE_ORCHESTRATOR
from aiq_agent.tokenomics.profile import PHASE_PLANNER
from aiq_agent.tokenomics.profile import PHASE_RESEARCHER


def _payload(
    event_type: str,
    ts: float,
    uuid: str = "step-uuid",
    **kwargs: object,
) -> dict:
    p: dict = {"event_type": event_type, "event_timestamp": ts, "UUID": uuid}
    p.update(kwargs)
    return {"payload": p}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"subagent_type": "planner-agent"}, "planner-agent"),
        ({"subagent_type": "researcher-agent"}, "researcher-agent"),
        ("{'subagent_type': 'planner-agent', 'description': 'x'}", "planner-agent"),
        ("malformed but researcher-agent string", "researcher-agent"),
    ],
)
def test_extract_subagent_type(raw, expected):
    assert _extract_subagent_type(raw) == expected


def test_extract_subagent_type_none():
    assert _extract_subagent_type(None) is None
    assert _extract_subagent_type({}) is None
    assert _extract_subagent_type("no marker here") is None


def test_build_task_windows_closes_pairs():
    steps = [
        _payload(
            "TOOL_START",
            10.0,
            uuid="t1",
            name="task",
            data={"input": {"subagent_type": "planner-agent"}},
        ),
        _payload("TOOL_END", 20.0, uuid="t1", name="task"),
    ]
    wins = _build_task_windows(steps)
    assert len(wins) == 1
    assert wins[0].subagent_type == "planner-agent"
    assert wins[0].start_ts == 10.0
    assert wins[0].end_ts == 20.0


def test_build_task_windows_string_input():
    steps = [
        _payload(
            "TOOL_START",
            1.0,
            uuid="u",
            name="task",
            data={"input": "{'subagent_type': 'researcher-agent'}"},
        ),
        _payload("TOOL_END", 2.0, uuid="u", name="task"),
    ]
    wins = _build_task_windows(steps)
    assert len(wins) == 1
    assert wins[0].phase == PHASE_RESEARCHER


def test_infer_phase_orchestrator_outside_windows():
    wins = [_TaskWindow(uuid="a", subagent_type="planner-agent", start_ts=10.0, end_ts=20.0)]
    assert _infer_phase(5.0, wins) == PHASE_ORCHESTRATOR
    assert _infer_phase(25.0, wins) == PHASE_ORCHESTRATOR


def test_infer_phase_inside_window():
    wins = [_TaskWindow(uuid="a", subagent_type="planner-agent", start_ts=10.0, end_ts=20.0)]
    assert _infer_phase(15.0, wins) == PHASE_PLANNER


def test_infer_phase_first_match_wins_on_overlap():
    planner = _TaskWindow(uuid="p", subagent_type="planner-agent", start_ts=10.0, end_ts=25.0)
    researcher = _TaskWindow(uuid="r", subagent_type="researcher-agent", start_ts=15.0, end_ts=30.0)
    ts = 18.0
    assert _infer_phase(ts, [planner, researcher]) == PHASE_PLANNER
    assert _infer_phase(ts, [researcher, planner]) == PHASE_RESEARCHER


def _minimal_pricing() -> PricingRegistry:
    return PricingRegistry.from_dict(
        {
            "models": {
                "test-model": {
                    "input_per_1m_tokens": 1.0,
                    "output_per_1m_tokens": 2.0,
                },
            },
            "default": {"input_per_1m_tokens": 1.0, "output_per_1m_tokens": 2.0},
            "tools": {},
        }
    )


def _llm_end(ts: float, uuid: str, span_ts: float | None = None) -> dict:
    body = {
        "event_type": "LLM_END",
        "event_timestamp": ts,
        "UUID": uuid,
        "name": "test-model",
        "usage_info": {
            "token_usage": {
                "prompt_tokens": 1000,
                "cached_tokens": 0,
                "completion_tokens": 500,
            },
        },
    }
    if span_ts is not None:
        body["span_event_timestamp"] = span_ts
    return {"payload": body}


def test_parse_trace_end_to_end(tmp_path: Path):
    """Orchestrator LLM outside task; planner LLM inside task window; one tool call."""
    steps = [
        _payload("WORKFLOW_START", 100.0, uuid="w0", data={"input": "my question?"}),
        _llm_end(101.0, "l0", span_ts=100.5),
        _payload(
            "TOOL_START",
            102.0,
            uuid="task1",
            name="task",
            data={"input": {"subagent_type": "planner-agent"}},
        ),
        _llm_end(103.0, "l1", span_ts=102.5),
        _payload("TOOL_START", 103.5, uuid="tool-a", name="search_tool"),
        _payload("TOOL_END", 104.0, uuid="tool-a", name="search_tool"),
        _payload("TOOL_END", 105.0, uuid="task1", name="task"),
        _payload("WORKFLOW_END", 106.0, uuid="w1"),
    ]
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps([{"request_number": 0, "intermediate_steps": steps}]), encoding="utf-8")

    profiles = parse_trace(str(trace_path), _minimal_pricing())
    assert len(profiles) == 1
    prof = profiles[0]
    assert prof.request_index == 0
    assert prof.question == "my question?"
    assert prof.duration_s == pytest.approx(6.0)
    assert prof.total_llm_calls == 2
    assert prof.tool_calls.get("search_tool") == 1

    orch = [p for p in prof.phases if p.phase == PHASE_ORCHESTRATOR]
    plan = [p for p in prof.phases if p.phase == PHASE_PLANNER]
    assert len(orch) == 1 and orch[0].llm_calls == 1
    assert len(plan) == 1 and plan[0].llm_calls == 1

    assert prof.llm_call_events[0]["phase"] == PHASE_ORCHESTRATOR
    assert prof.llm_call_events[1]["phase"] == PHASE_PLANNER


def test_parse_trace_skips_broken_request(tmp_path: Path):
    bad = [{"request_number": 0, "intermediate_steps": "not-a-list"}]
    good_steps = [
        _payload("WORKFLOW_START", 1.0, data={"input": ""}),
        _payload("WORKFLOW_END", 2.0),
    ]
    good = [{"request_number": 1, "intermediate_steps": good_steps}]
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(bad + good), encoding="utf-8")

    profiles = parse_trace(str(trace_path), _minimal_pricing())
    assert len(profiles) == 1
    assert profiles[0].request_index == 1
