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

"""
NAT trace → list[RequestProfile]
=================================

Converts a NAT profiler trace JSON file (produced by ``nat eval``) into
structured :class:`~aiq_agent.tokenomics.profile.RequestProfile` objects
ready for the tokenomics HTML report.

Architecture note
-----------------
The workflow is registered as ``deep_research_agent``.  NAT 1.5.0 traces still
emit ``FUNCTION_START`` / ``FUNCTION_END`` for **tools** (e.g. search helpers),
but **planner-agent** and **researcher-agent** runs live inside the ``task``
tool: they do not get distinct ``FUNCTION_*`` names.  Traces from this stack
typically have no per-step ``function_ancestry`` (or equivalent) carrying
subagent identity — calling ``subagent.ainvoke()`` does not surface as separate
NAT function scopes for Planner vs Researcher.

Subagent attribution is therefore inferred post-hoc via timing windows: every
``task`` TOOL_START/END pair brackets one subagent invocation and carries
``subagent_type`` in its input.  For each ``LLM_END`` we use that step's
``event_timestamp`` (completion time, not ``span_event_timestamp``): if it
lies inside a task window, the call is attributed to that phase; otherwise
**orchestrator-phase**.

``_build_task_windows`` appends windows in ``task`` TOOL_END order.
``_infer_phase`` returns the **first** window in that list whose bounds contain
``ts``.  Overlapping researcher windows share the same phase label, so order is
unimportant in the common parallel-researcher case.

If NAT later attaches subagent phase directly on each step (e.g.
``function_ancestry`` or explicit ``FUNCTION_*`` scopes for subagents),
``_infer_phase`` can be replaced with a field read and the rest of this module
can stay the same.
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from .pricing import PricingRegistry
from .profile import PHASE_ORCHESTRATOR
from .profile import PHASE_PLANNER
from .profile import PHASE_RESEARCHER
from .profile import PhaseStats
from .profile import RequestProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass
class _TaskWindow:
    """Time span of a single subagent (task tool) invocation."""

    uuid: str
    subagent_type: str  # "planner-agent" | "researcher-agent"
    start_ts: float
    end_ts: float = field(default=0.0)

    @property
    def phase(self) -> str:
        if self.subagent_type == "planner-agent":
            return PHASE_PLANNER
        return PHASE_RESEARCHER  # any other subagent_type → researcher-phase


def _extract_subagent_type(raw_input: Any) -> str | None:
    """Pull subagent_type out of the task tool's input field."""
    if isinstance(raw_input, dict):
        return raw_input.get("subagent_type")
    if isinstance(raw_input, str):
        # NAT stores tool inputs as Python-repr strings, not JSON
        try:
            parsed = ast.literal_eval(raw_input)
            if isinstance(parsed, dict):
                return parsed.get("subagent_type")
        except Exception:
            pass
        # Last resort: substring scan (handles malformed reprs)
        for candidate in ("planner-agent", "researcher-agent"):
            if candidate in raw_input:
                return candidate
    return None


def _build_task_windows(steps: list[dict]) -> list[_TaskWindow]:
    """Build a list of completed task-tool windows from a request's steps."""
    open_windows: dict[str, _TaskWindow] = {}
    closed: list[_TaskWindow] = []

    for step in steps:
        payload = step["payload"]
        event_type = payload["event_type"]
        name = payload.get("name", "")
        uuid = payload["UUID"]
        ts = payload["event_timestamp"]

        if event_type == "TOOL_START" and name == "task":
            raw_input = (payload.get("data") or {}).get("input")
            subagent_type = _extract_subagent_type(raw_input)
            if subagent_type:
                open_windows[uuid] = _TaskWindow(uuid=uuid, subagent_type=subagent_type, start_ts=ts)
            else:
                logger.debug("task TOOL_START missing subagent_type, uuid=%s", uuid)

        elif event_type == "TOOL_END" and name == "task":
            win = open_windows.pop(uuid, None)
            if win is not None:
                win.end_ts = ts
                closed.append(win)

    if open_windows:
        logger.warning("%d task windows never closed (truncated trace?)", len(open_windows))

    return closed


def _infer_phase(ts: float, windows: list[_TaskWindow]) -> str:
    """
    Return the phase label for an LLM call from its ``LLM_END`` time ``ts``.

    ``windows`` is ordered by ``task`` TOOL_END (see ``_build_task_windows``).
    The first window with ``start_ts <= ts <= end_ts`` wins.  Overlapping
    researcher windows all map to ``researcher-phase`` anyway.
    """
    for win in windows:
        if win.start_ts <= ts <= win.end_ts:
            return win.phase
    return PHASE_ORCHESTRATOR


def _parse_request(request_index: int, steps: list[dict], pricing: PricingRegistry) -> RequestProfile:
    """Convert one request's step list into a RequestProfile."""

    # --- Workflow timing and question ---
    wf_start_ts = wf_end_ts = 0.0
    question = ""
    for step in steps:
        payload = step["payload"]
        et = payload["event_type"]
        if et == "WORKFLOW_START":
            wf_start_ts = payload["event_timestamp"]
            question = (payload.get("data") or {}).get("input") or ""
        elif et == "WORKFLOW_END":
            wf_end_ts = payload["event_timestamp"]

    duration_s = max(0.0, wf_end_ts - wf_start_ts)

    # --- Subagent phase windows ---
    task_windows = _build_task_windows(steps)

    # --- Single forward pass: accumulate all events ---
    phase_model_stats: dict[tuple[str, str], PhaseStats] = {}
    model_call_counters: dict[str, int] = {}
    llm_call_events: list[dict] = []
    tool_call_events: list[dict] = []
    tool_calls: dict[str, int] = {}
    tool_start_times: dict[str, tuple[str, float]] = {}  # uuid -> (name, start_ts)

    for step in steps:
        payload = step["payload"]
        et = payload["event_type"]
        uuid = payload["UUID"]
        ts = payload["event_timestamp"]

        if et == "TOOL_START":
            name = payload.get("name") or "unknown"
            tool_start_times[uuid] = (name, ts)

        elif et == "TOOL_END":
            name = payload.get("name") or "unknown"
            tool_calls[name] = tool_calls.get(name, 0) + 1
            dur_s = 0.0
            if uuid in tool_start_times:
                _, start_ts = tool_start_times.pop(uuid)
                dur_s = max(0.0, ts - start_ts)
            tool_price = pricing.get_tool(name)
            tool_call_events.append(
                {
                    "tool": name,
                    "dur_s": round(dur_s, 3),
                    "cost_usd": tool_price.cost_per_call,
                }
            )

        elif et == "LLM_END":
            # span_event_timestamp is set by LangchainProfilerHandler at LLM_START
            span_ts = payload.get("span_event_timestamp", ts)
            model = payload.get("name") or "unknown"
            usage = (payload.get("usage_info") or {}).get("token_usage") or {}

            prompt_tokens = usage.get("prompt_tokens", 0)
            cached_tokens = usage.get("cached_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            reasoning_tokens = usage.get("reasoning_tokens", 0)

            dur_s = max(0.0, ts - span_ts)
            tps = completion_tokens / dur_s if dur_s > 0 else 0.0

            # Window match uses LLM_END event_timestamp (completion), not span_event_timestamp.
            phase = _infer_phase(ts, task_windows)
            key = (phase, model)

            if key not in phase_model_stats:
                phase_model_stats[key] = PhaseStats(phase=phase, model=model)

            try:
                price = pricing.get(model)
                cost = price.cost(prompt_tokens, cached_tokens, completion_tokens)
                savings = price.cache_savings(cached_tokens)
            except KeyError:
                logger.warning("No price for model %r — cost will be 0", model)
                cost = savings = 0.0

            ps = phase_model_stats[key]
            ps.llm_calls += 1
            ps.prompt_tokens += prompt_tokens
            ps.cached_tokens += cached_tokens
            ps.completion_tokens += completion_tokens
            ps.cost_usd += cost
            ps.cache_savings_usd += savings

            # Per-call observation (for distribution charts)
            call_idx = model_call_counters.get(model, 0)
            model_call_counters[model] = call_idx + 1

            llm_call_events.append(
                {
                    "uuid": uuid,
                    "isl": prompt_tokens,
                    "osl": completion_tokens,
                    "cached": cached_tokens,
                    "reasoning": reasoning_tokens,
                    "dur_s": round(dur_s, 3),
                    "tps": round(tps, 2),
                    "model": model,
                    "phase": phase,
                    "call_idx": call_idx,
                }
            )

    # --- Roll up to request-level totals ---
    phases = list(phase_model_stats.values())
    total_tool_cost_usd = sum(ev["cost_usd"] for ev in tool_call_events)
    return RequestProfile(
        request_index=request_index,
        question=question,
        duration_s=duration_s,
        phases=phases,
        tool_calls=tool_calls,
        llm_call_events=llm_call_events,
        tool_call_events=tool_call_events,
        total_llm_calls=sum(p.llm_calls for p in phases),
        total_prompt_tokens=sum(p.prompt_tokens for p in phases),
        total_cached_tokens=sum(p.cached_tokens for p in phases),
        total_completion_tokens=sum(p.completion_tokens for p in phases),
        total_cost_usd=sum(p.cost_usd for p in phases),
        total_tool_cost_usd=total_tool_cost_usd,
        total_cache_savings_usd=sum(p.cache_savings_usd for p in phases),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_trace(path: str, pricing: PricingRegistry) -> list[RequestProfile]:
    """
    Parse a NAT profiler trace JSON file and return one
    :class:`~aiq_agent.tokenomics.profile.RequestProfile` per request.

    Parameters
    ----------
    path:
        Path to the ``all_requests_profiler_traces.json`` file produced by
        ``nat eval``.
    pricing:
        A :class:`~aiq_agent.tokenomics.pricing.PricingRegistry` built from
        the ``tokenomics.pricing`` section of the eval config YAML.
    """
    with open(path) as f:
        data = json.load(f)

    profiles = []
    for item in data:
        idx = item.get("request_number", len(profiles))
        steps = item.get("intermediate_steps", [])
        try:
            profiles.append(_parse_request(idx, steps, pricing))
        except Exception:
            logger.exception("Failed to parse request %d — skipping", idx)

    return profiles
