#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Generate a self-contained tokenomics HTML report from a NAT profiler trace.

Single-run
----------
python -m aiq_agent.tokenomics.report \\
    --trace  results/all_requests_profiler_traces.json \\
    --config configs/config_tokenomics_pricing.yml \\
    [--output results/tokenomics_report.html]

Comparison (two or more runs)
------------------------------
python -m aiq_agent.tokenomics.report \\
    --trace results/run_a/all_requests_profiler_traces.json \\
    --trace results/run_b/all_requests_profiler_traces.json \\
    --config configs/config_tokenomics_pricing.yml

Passing ``--trace`` more than once activates comparison mode: all existing
tabs show Run A data unchanged, and a new ``🔀 Compare`` tab appears with
side-by-side cost/token charts and a per-query delta table.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from .nat_adapter import parse_trace
from .pricing import PricingRegistry
from .profile import PHASE_ORCHESTRATOR
from .profile import PHASE_ORDER
from .profile import PHASE_PLANNER
from .profile import PHASE_RESEARCHER
from .profile import RequestProfile

PHASE_LABELS = {
    PHASE_ORCHESTRATOR: "Orchestrator",
    PHASE_PLANNER: "Planner",
    PHASE_RESEARCHER: "Researcher",
}


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _pct(data: list, p: float) -> float:
    """Return the p-th percentile of ``data`` (linear interpolation)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _latency_stats(durations_s: list[float]) -> dict:
    if not durations_s:
        return {"count": 0, "p50_ms": 0.0, "p90_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0}
    ms = [d * 1000.0 for d in durations_s]
    return {
        "count": len(ms),
        "p50_ms": round(_pct(ms, 50), 2),
        "p90_ms": round(_pct(ms, 90), 2),
        "p99_ms": round(_pct(ms, 99), 2),
        "max_ms": round(max(ms), 2),
        "mean_ms": round(sum(ms) / len(ms), 2),
    }


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------


def _load_csv_predictions(trace_path: str) -> dict[str, float]:
    """
    Load NOVA-Predicted-OSL values from standardized_data_all.csv if it lives
    alongside the trace file.  Returns UUID → predicted_osl mapping.
    """
    csv_path = Path(trace_path).parent / "standardized_data_all.csv"
    if not csv_path.exists():
        return {}
    predictions: dict[str, float] = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("event_type") == "LLM_START" and row.get("NOVA-Predicted-OSL") and row.get("UUID"):
                try:
                    predictions[row["UUID"]] = float(row["NOVA-Predicted-OSL"])
                except ValueError:
                    pass
    return predictions


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------


def _build_report_data(
    profiles: list[RequestProfile],
    pricing: PricingRegistry,
    config_path: str,
    predicted_osl_map: dict[str, float] | None = None,
) -> dict:
    # Flatten all per-call observations
    all_llm: list[dict] = []
    all_tool: list[dict] = []
    for prof in profiles:
        all_llm.extend(prof.llm_call_events)
        all_tool.extend(prof.tool_call_events)

    # ── Token stats by model ──────────────────────────────────────────────
    m_isls: dict[str, list] = defaultdict(list)
    m_osls: dict[str, list] = defaultdict(list)
    m_tps: dict[str, list] = defaultdict(list)
    m_tot: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "total_isl": 0,
            "total_osl": 0,
            "total_cached": 0,
            "total_reasoning": 0,
        }
    )
    for ev in all_llm:
        m = ev["model"]
        m_isls[m].append(ev["isl"])
        m_osls[m].append(ev["osl"])
        if ev["tps"] > 0:
            m_tps[m].append(ev["tps"])
        t = m_tot[m]
        t["calls"] += 1
        t["total_isl"] += ev["isl"]
        t["total_osl"] += ev["osl"]
        t["total_cached"] += ev["cached"]
        t["total_reasoning"] += ev["reasoning"]

    by_model_tokens: dict[str, dict] = {}
    for m, t in m_tot.items():
        isls = m_isls[m]
        osls = m_osls[m]
        tps_vals = m_tps[m]
        by_model_tokens[m] = {
            "calls": t["calls"],
            "total_isl": t["total_isl"],
            "total_osl": t["total_osl"],
            "total_cached": t["total_cached"],
            "total_reasoning": t["total_reasoning"],
            "isl_mean": round(sum(isls) / len(isls), 1) if isls else 0.0,
            "isl_p50": round(_pct(isls, 50), 1),
            "isl_p90": round(_pct(isls, 90), 1),
            "isl_p99": round(_pct(isls, 99), 1),
            "isl_max": max(isls) if isls else 0,
            "isl_min": min(isls) if isls else 0,
            "osl_mean": round(sum(osls) / len(osls), 1) if osls else 0.0,
            "osl_p50": round(_pct(osls, 50), 1),
            "osl_p90": round(_pct(osls, 90), 1),
            "osl_p99": round(_pct(osls, 99), 1),
            "osl_max": max(osls) if osls else 0,
            "cache_rate": t["total_cached"] / t["total_isl"] if t["total_isl"] > 0 else 0.0,
            "tps_mean": round(sum(tps_vals) / len(tps_vals), 2) if tps_vals else 0.0,
            "tps_p50": round(_pct(tps_vals, 50), 2) if tps_vals else 0.0,
            "tps_p90": round(_pct(tps_vals, 90), 2) if tps_vals else 0.0,
        }

    # ── Token stats by component (phase) ─────────────────────────────────
    ph_isls: dict[str, list] = defaultdict(list)
    ph_osls: dict[str, list] = defaultdict(list)
    ph_tot: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "total_isl": 0,
            "total_osl": 0,
            "total_cached": 0,
            "total_reasoning": 0,
        }
    )
    for ev in all_llm:
        ph = ev["phase"]
        ph_isls[ph].append(ev["isl"])
        ph_osls[ph].append(ev["osl"])
        t = ph_tot[ph]
        t["calls"] += 1
        t["total_isl"] += ev["isl"]
        t["total_osl"] += ev["osl"]
        t["total_cached"] += ev["cached"]
        t["total_reasoning"] += ev["reasoning"]

    by_component_tokens: dict[str, dict] = {}
    for ph in PHASE_ORDER:
        if ph not in ph_tot:
            continue
        t = ph_tot[ph]
        isls = ph_isls[ph]
        osls = ph_osls[ph]
        label = PHASE_LABELS.get(ph, ph)
        by_component_tokens[label] = {
            "calls": t["calls"],
            "total_isl": t["total_isl"],
            "total_osl": t["total_osl"],
            "total_cached": t["total_cached"],
            "total_reasoning": t["total_reasoning"],
            "isl_mean": round(sum(isls) / len(isls), 1) if isls else 0.0,
            "isl_p50": round(_pct(isls, 50), 1),
            "isl_p90": round(_pct(isls, 90), 1),
            "isl_p99": round(_pct(isls, 99), 1),
            "isl_max": max(isls) if isls else 0,
            "osl_mean": round(sum(osls) / len(osls), 1) if osls else 0.0,
            "osl_p50": round(_pct(osls, 50), 1),
            "osl_p90": round(_pct(osls, 90), 1),
            "osl_p99": round(_pct(osls, 99), 1),
            "osl_max": max(osls) if osls else 0,
            "cache_rate": t["total_cached"] / t["total_isl"] if t["total_isl"] > 0 else 0.0,
        }

    # ── ISL growth: avg ISL by sequential call index, per model ───────────
    growth_data: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for ev in all_llm:
        growth_data[ev["model"]][ev["call_idx"]].append(ev["isl"])

    isl_growth: dict[str, list[dict]] = {}
    for model in sorted(growth_data):
        idx_map = growth_data[model]
        isl_growth[model] = [
            {"idx": idx, "avg_isl": round(sum(v) / len(v), 1), "n": len(v)}
            for idx in sorted(idx_map)
            for v in [idx_map[idx]]
        ]

    # ── ISL vs latency sample ─────────────────────────────────────────────
    isl_latency_sample = [
        {"isl": ev["isl"], "dur_s": ev["dur_s"], "model": ev["model"], "osl": ev["osl"]}
        for ev in all_llm
        if ev["dur_s"] > 0
    ]

    # ── Sys-prompt estimate (min ISL per model) ───────────────────────────
    sys_prompt_est = {m: min(m_isls[m]) for m in m_isls if m_isls[m]}

    # ── LLM latency per model ─────────────────────────────────────────────
    m_durs: dict[str, list] = defaultdict(list)
    for ev in all_llm:
        if ev["dur_s"] > 0:
            m_durs[ev["model"]].append(ev["dur_s"])

    llm_latency = {m: _latency_stats(durs) for m, durs in m_durs.items()}

    # ── Tool latency per tool ─────────────────────────────────────────────
    t_durs: dict[str, list] = defaultdict(list)
    for ev in all_tool:
        if ev["dur_s"] > 0:
            t_durs[ev["tool"]].append(ev["dur_s"])

    tool_latency = {tool: _latency_stats(durs) for tool, durs in t_durs.items()}

    # ── Cost by model ─────────────────────────────────────────────────────
    by_model_cost: dict[str, float] = defaultdict(float)
    for prof in profiles:
        for ps in prof.phases:
            by_model_cost[ps.model] += ps.cost_usd

    # ── Cost by phase ─────────────────────────────────────────────────────
    by_phase_cost: dict[str, float] = {}
    for ph in PHASE_ORDER:
        total = sum(prof.cost_for_phase(ph) for prof in profiles)
        if total > 0:
            by_phase_cost[PHASE_LABELS.get(ph, ph)] = round(total, 6)

    # ── Per-query list ────────────────────────────────────────────────────
    per_query = []
    for prof in profiles:
        pq_by_phase = {}
        for ph in PHASE_ORDER:
            label = PHASE_LABELS.get(ph, ph)
            cost = prof.cost_for_phase(ph)
            if cost > 0:
                pq_by_phase[label] = round(cost, 6)
        per_query.append(
            {
                "id": prof.request_index,
                "question": prof.question,
                "cost_usd": round(prof.grand_total_cost_usd, 6),
                "llm_cost_usd": round(prof.total_cost_usd, 6),
                "tool_cost_usd": round(prof.total_tool_cost_usd, 6),
                "input_tokens": prof.total_prompt_tokens,
                "output_tokens": prof.total_completion_tokens,
                "cached_tokens": prof.total_cached_tokens,
                "entry_count": prof.total_llm_calls,
                "duration_s": round(prof.duration_s, 2),
                "by_phase": pq_by_phase,
            }
        )

    # ── Pricing snapshot ──────────────────────────────────────────────────
    pricing_snapshot: dict[str, dict] = {}
    for model in pricing.known_models():
        p = pricing.get(model)
        pricing_snapshot[model] = {
            "input_per_1m_tokens": p.input_per_1m_tokens,
            "cached_input_per_1m_tokens": p.cached_input_per_1m_tokens,
            "output_per_1m_tokens": p.output_per_1m_tokens,
        }
    if pricing._default is not None:
        pricing_snapshot["default"] = {
            "input_per_1m_tokens": pricing._default.input_per_1m_tokens,
            "cached_input_per_1m_tokens": pricing._default.cached_input_per_1m_tokens,
            "output_per_1m_tokens": pricing._default.output_per_1m_tokens,
        }

    # ── Tool cost aggregation ─────────────────────────────────────────────
    by_tool_cost: dict[str, dict] = defaultdict(lambda: {"calls": 0, "total_cost_usd": 0.0})
    for ev in all_tool:
        entry = by_tool_cost[ev["tool"]]
        entry["calls"] += 1
        entry["total_cost_usd"] += ev.get("cost_usd", 0.0)
    by_tool_cost = {k: dict(v) for k, v in by_tool_cost.items()}

    # Tool pricing snapshot (only configured tools)
    tool_pricing_snapshot = {name: pricing.get_tool(name).cost_per_call for name in pricing.known_tools()}

    # ── Predicted vs actual OSL (from NOVA-Predicted-OSL in CSV) ─────────
    # NOTE: in current NAT traces, NOVA-Predicted-OSL is filled post-hoc with
    # the actual completion tokens, so predicted == actual on every call.
    # The list is populated here for forward-compatibility; the chart is hidden
    # when all errors are zero (trivially perfect, not informative).
    predicted_vs_actual: list[dict] = []
    if predicted_osl_map:
        for ev in all_llm:
            pred = predicted_osl_map.get(ev.get("uuid", ""))
            if pred is not None:
                predicted_vs_actual.append(
                    {
                        "model": ev["model"],
                        "predicted": pred,
                        "actual": ev["osl"],
                        "phase": ev["phase"],
                    }
                )

    total_llm_cost = sum(p.total_cost_usd for p in profiles)
    total_tool_cost = sum(p.total_tool_cost_usd for p in profiles)
    grand_total = total_llm_cost + total_tool_cost
    return {
        "label": Path(config_path).name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "num_queries": len(profiles),
        "total_cost_usd": round(grand_total, 6),
        "llm_cost_usd": round(total_llm_cost, 6),
        "tool_cost_usd": round(total_tool_cost, 6),
        "avg_cost_usd": round(grand_total / len(profiles), 6) if profiles else 0.0,
        "cache_savings_usd": round(sum(p.total_cache_savings_usd for p in profiles), 6),
        "total_prompt_tokens": sum(p.total_prompt_tokens for p in profiles),
        "total_cached_tokens": sum(p.total_cached_tokens for p in profiles),
        "total_completion_tokens": sum(p.total_completion_tokens for p in profiles),
        "total_llm_calls": sum(p.total_llm_calls for p in profiles),
        "per_query": per_query,
        "by_model": dict(by_model_cost),
        "by_phase": by_phase_cost,
        "by_tool": by_tool_cost,
        "phase_order": [PHASE_LABELS.get(ph, ph) for ph in PHASE_ORDER],
        "llm_latency": llm_latency,
        "tool_latency": tool_latency,
        "pricing_snapshot": pricing_snapshot,
        "tool_pricing_snapshot": tool_pricing_snapshot,
        "token_stats": {
            "by_model": by_model_tokens,
            "by_component": by_component_tokens,
            "isl_growth": isl_growth,
            "isl_latency_sample": isl_latency_sample,
            "sys_prompt_est": sys_prompt_est,
            "predicted_vs_actual": predicted_vs_actual,
        },
    }


# ---------------------------------------------------------------------------
# Comparison data builder
# ---------------------------------------------------------------------------


def _build_comparison_data(run_datas: list[dict]) -> dict:
    """Return an A-vs-B comparison block to embed in the primary run's report_data.

    Only the first two runs are compared.  The per-query list is the UNION of
    both runs' query IDs so that queries unique to one run are still visible in
    the table (with null for the missing side).  The delta bar chart in the
    report only renders bars for queries present in both runs.
    """
    a = run_datas[0]
    b = run_datas[1]

    a_by_id = {q["id"]: q for q in a.get("per_query", [])}
    b_by_id = {q["id"]: q for q in b.get("per_query", [])}
    all_ids = sorted(set(a_by_id) | set(b_by_id))
    common_ids = set(a_by_id) & set(b_by_id)

    per_query_cmp = []
    for qid in all_ids:
        qa = a_by_id.get(qid)
        qb = b_by_id.get(qid)
        in_both = qa is not None and qb is not None

        cost_a = qa["cost_usd"] if qa else None
        cost_b = qb["cost_usd"] if qb else None
        if in_both:
            cost_delta: float | None = round(cost_b - cost_a, 6)  # type: ignore[operator]
            cost_pct: float | None = round((cost_delta / cost_a * 100) if cost_a else 0.0, 1)
        else:
            cost_delta = cost_pct = None

        per_query_cmp.append(
            {
                "id": qid,
                "question": (qa or qb).get("question", ""),  # type: ignore[union-attr]
                "cost_a": cost_a,
                "cost_b": cost_b,
                "cost_delta": cost_delta,
                "cost_pct": cost_pct,
                "isl_a": qa.get("input_tokens") if qa else None,
                "isl_b": qb.get("input_tokens") if qb else None,
                "osl_a": qa.get("output_tokens") if qa else None,
                "osl_b": qb.get("output_tokens") if qb else None,
                "duration_a": qa.get("duration_s") if qa else None,
                "duration_b": qb.get("duration_s") if qb else None,
                "llm_calls_a": qa.get("entry_count") if qa else None,
                "llm_calls_b": qb.get("entry_count") if qb else None,
                "in_both": in_both,
            }
        )

    cost_delta_total = b["total_cost_usd"] - a["total_cost_usd"]
    cost_pct_total = (cost_delta_total / a["total_cost_usd"] * 100) if a["total_cost_usd"] else 0.0
    prompt_a = a.get("total_prompt_tokens", 0)
    prompt_b = b.get("total_prompt_tokens", 0)

    return {
        "label_a": a["label"],
        "label_b": b["label"],
        "num_queries_a": a["num_queries"],
        "num_queries_b": b["num_queries"],
        "num_common_queries": len(common_ids),
        "total_cost_a": a["total_cost_usd"],
        "total_cost_b": b["total_cost_usd"],
        "llm_cost_a": a["llm_cost_usd"],
        "llm_cost_b": b["llm_cost_usd"],
        "total_llm_calls_a": a["total_llm_calls"],
        "total_llm_calls_b": b["total_llm_calls"],
        "cache_rate_a": round(a.get("total_cached_tokens", 0) / prompt_a, 4) if prompt_a else 0.0,
        "cache_rate_b": round(b.get("total_cached_tokens", 0) / prompt_b, 4) if prompt_b else 0.0,
        "cost_delta": round(cost_delta_total, 6),
        "cost_pct_change": round(cost_pct_total, 1),
        "by_model_a": a.get("by_model", {}),
        "by_model_b": b.get("by_model", {}),
        "by_phase_a": a.get("by_phase", {}),
        "by_phase_b": b.get("by_phase", {}),
        "per_query": per_query_cmp,
    }


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>AIQ Tokenomics Report</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --surface2: #1f2937;
    --border: #30363d; --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --blue: #58a6ff; --orange: #d29922;
    --purple: #bc8cff; --red: #f85149; --teal: #39d353;
    --nvidia: #76b900;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
  }
  header {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 14px 24px; display: flex; align-items: center; gap: 16px;
    flex-wrap: wrap;
  }
  header h1 { font-size: 18px; font-weight: 600; color: var(--nvidia); }
  header .meta { color: var(--muted); font-size: 13px; }
  nav { background: var(--surface); border-bottom: 1px solid var(--border); display: flex; overflow-x: auto; }
  nav button {
    background: none; border: none; color: var(--muted); padding: 12px 20px;
    cursor: pointer; font-size: 13px; font-weight: 500;
    border-bottom: 2px solid transparent; white-space: nowrap;
    transition: color .15s, border-color .15s;
  }
  nav button:hover { color: var(--text); }
  nav button.active { color: var(--blue); border-bottom-color: var(--blue); }
  main { padding: 20px 24px; max-width: 1600px; margin: 0 auto; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden; margin-bottom: 16px;
  }
  .card-header { padding: 10px 16px 8px; border-bottom: 1px solid var(--border); font-weight: 600; font-size: 13px; }
  .card-sub { color: var(--muted); font-size: 11px; font-weight: 400; margin-top: 2px; }
  .card-body { padding: 4px; }
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px; margin-bottom: 16px;
  }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .stat .label {
    color: var(--muted); font-size: 12px; margin-bottom: 4px;
    text-transform: uppercase; letter-spacing: .5px;
  }
  .stat .value { font-size: 24px; font-weight: 700; }
  .stat .sub { color: var(--muted); font-size: 11px; margin-top: 4px; }
  .stat.green .value { color: var(--green); }
  .stat.blue .value { color: var(--blue); }
  .stat.orange .value { color: var(--orange); }
  .stat.purple .value { color: var(--purple); }
  .stat.red .value { color: var(--red); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th {
    background: var(--surface2); padding: 10px 14px; text-align: left;
    color: var(--muted); font-weight: 600; font-size: 12px;
    text-transform: uppercase; letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
  }
  td { padding: 9px 14px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--surface2); }
  .price-table td:nth-child(2), .price-table td:nth-child(3),
  .price-table td:nth-child(4) { color: var(--green); font-family: monospace; }
  @media (max-width: 900px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<header>
  <h1>⚡ AIQ Tokenomics Report</h1>
  <span class="meta" id="headerMeta"></span>
</header>

<nav>
  <button class="active" onclick="showTab('overview',this)">📊 Overview</button>
  <button onclick="showTab('cost',this)">💰 Cost</button>
  <button onclick="showTab('latency',this)">⏱ Latency</button>
  <button onclick="showTab('tokens',this)">🪙 Tokens</button>
  <button onclick="showTab('efficiency',this)">📐 Efficiency</button>
  <button onclick="showTab('pricing',this)">🏷 Pricing</button>
  <button onclick="showTab('detail',this)">📋 Per-Query</button>
  <button id="compareBtn" style="display:none" onclick="showTab('compare',this)">🔀 Compare</button>
</nav>

<main>

<!-- ── OVERVIEW ─────────────────────────────────────────────────────────── -->
<div id="tab-overview" class="tab-content active">
  <div class="stat-grid" id="overviewStats"></div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header">🤖 Cost by Model
        <div class="card-sub">Which model is consuming most of the budget?</div>
      </div>
      <div class="card-body"><div id="overviewModelBar"></div></div>
    </div>
    <div class="card">
      <div class="card-header">🏗 Cost by Phase
        <div class="card-sub">Orchestrator = reasoning overhead; Researcher = parallel search calls.
          High Researcher share means many tool-heavy sub-tasks.</div>
      </div>
      <div class="card-body"><div id="overviewPhaseBar"></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-header">📋 Per-Query Summary</div>
    <div class="card-body" style="padding:0">
      <table id="overviewTable">
        <thead><tr>
          <th>Query #</th><th>Cost ($)</th><th>Prompt (ISL)</th><th>Completion (OSL)</th>
          <th>Cached</th><th>Cache %</th><th>LLM Calls</th><th>Duration (s)</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ── COST ──────────────────────────────────────────────────────────────── -->
<div id="tab-cost" class="tab-content">
  <div class="grid-2">
    <div class="card">
      <div class="card-header">🥧 Cost Split by Model
        <div class="card-sub">Hover for exact values. A single dominant slice means one model drives
          nearly all spend.</div>
      </div>
      <div class="card-body"><div id="costPie"></div></div>
    </div>
    <div class="card">
      <div class="card-header">🏗 Cost by Phase
        <div class="card-sub">Total spend per phase summed across all queries. Orchestrator dominance
          is normal; unexpectedly high Researcher cost suggests overly broad search loops.</div>
      </div>
      <div class="card-body"><div id="costPhaseBar"></div></div>
    </div>
  </div>
  <div id="toolCostCard" class="card">
    <div class="card-header">🔍 Tool API Cost by Tool
      <div class="card-sub">Per-call cost × invocation count for each tool. These charges are separate
        from LLM token costs. High search costs relative to LLM costs suggest reducing max_results or
        switching to a cheaper search provider.</div>
    </div>
    <div class="card-body"><div id="toolCostBar"></div></div>
  </div>
  <div id="costHistogramCard" class="card">
    <div class="card-header">📈 Per-Query Cost Distribution
      <div class="card-sub">Shape of the distribution matters: a long right tail means a small number
        of expensive queries are inflating average cost.</div>
    </div>
    <div class="card-body"><div id="costHistogram"></div></div>
  </div>
  <div class="card">
    <div class="card-header">📦 Cost by Phase per Query
      <div class="card-sub">Spot outlier queries and identify which phase drove the extra cost. Uniform
        bars = consistent workload; spikes = difficult queries.</div>
    </div>
    <div class="card-body"><div id="costPerQueryStack"></div></div>
  </div>
</div>

<!-- ── LATENCY ───────────────────────────────────────────────────────────── -->
<div id="tab-latency" class="tab-content">
  <div class="grid-2">
    <div class="card">
      <div class="card-header">📊 LLM Latency Percentiles by Model
        <div class="card-sub">A large gap between p50 and p99 means occasional very long completions —
          usually caused by high OSL. If p50 is already slow, the bottleneck is network or server load.
        </div>
      </div>
      <div class="card-body"><div id="llmLatencyBar"></div></div>
    </div>
    <div class="card">
      <div class="card-header">🔍 Tool Latency Percentiles
        <div class="card-sub">Search/web tools typically run 3–8 s. p90 above 10 s signals a retrieval
          bottleneck that adds directly to total query time.</div>
      </div>
      <div class="card-body"><div id="toolLatencyBar"></div></div>
    </div>
  </div>
</div>

<!-- ── TOKENS ────────────────────────────────────────────────────────────── -->
<div id="tab-tokens" class="tab-content">
  <div class="stat-grid" id="tokenStats"></div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header">📥 ISL (Input Sequence Length) — p50 / p90 / p99 by Model
        <div class="card-sub">Prompt token counts sent to each model. A rising p99 vs p50 means some calls
          hit much larger contexts — check ISL Growth below to see when.</div>
      </div>
      <div class="card-body"><div id="islBar"></div></div>
    </div>
    <div class="card">
      <div class="card-header">📤 OSL (Output Sequence Length) — p50 / p90 / p99 by Model
        <div class="card-sub">Completion token counts. High p99 OSL means some calls produce very long
          reasoning chains or verbose outputs, which directly drives both cost and latency.</div>
      </div>
      <div class="card-body"><div id="oslBar"></div></div>
    </div>
  </div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header">📈 Context Accumulation — Avg ISL by Call Index
        <div class="card-sub">How prompt size grows over sequential LLM calls within a query. An upward
          slope means the model is accumulating conversation history. A plateau suggests caching or a
          fresh-start pattern. The dashed line is the estimated system-prompt floor (minimum ISL
          observed).</div>
      </div>
      <div class="card-body"><div id="islGrowth"></div></div>
    </div>
    <div class="card">
      <div class="card-header">⚡ Throughput — Completion Tokens / Second
        <div class="card-sub">Inference speed per model. Low TPS with small OSL often indicates network
          round-trip overhead rather than slow generation. Compare models to spot which is the throughput
          bottleneck.</div>
      </div>
      <div class="card-body"><div id="tpsBar"></div></div>
    </div>
  </div>
  <div id="predVsActualCard" class="card">
    <div class="card-header">🔮 NOVA-Predicted vs Actual OSL
      <div class="card-sub">Each dot is one LLM call. Points on the diagonal line = perfect prediction.
        Points above = model generated more than predicted (underestimate). Points below = model generated
        less (overestimate). Tight clustering around the diagonal means NAT's routing hints are accurate.
      </div>
    </div>
    <div class="card-body"><div id="predVsActualScatter"></div></div>
  </div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header">🗜 Token Budget — Cached vs Uncached vs Completion
        <div class="card-sub">Green = tokens served from cache (billed at the cheaper cached rate). Grey
          = uncached prompt tokens (full price). Blue = completion tokens (most expensive per token).
          Maximise green to reduce cost.</div>
      </div>
      <div class="card-body"><div id="cacheBreakdown"></div></div>
    </div>
    <div class="card">
      <div class="card-header">🔗 ISL vs Latency — Is Prompt Size the Bottleneck?
        <div class="card-sub">Each dot is one LLM call. A diagonal trend means longer prompts take longer
          (prompt-bound). A flat cloud means latency is driven by output length or server capacity, not
          context size.</div>
      </div>
      <div class="card-body"><div id="islLatencyScatter"></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-header">🏗 Token Mix by Phase
      <div class="card-sub">Total tokens consumed across Orchestrator / Planner / Researcher phases.
        Cached (green) vs uncached (grey) prompt tokens show how well each phase leverages the prompt
        cache. Reasoning tokens (purple) are non-billed thinking tokens where applicable.</div>
    </div>
    <div class="card-body"><div id="componentTokenStack"></div></div>
  </div>
  <div class="card">
    <div class="card-header">📋 Token Summary Table (by model)</div>
    <div class="card-body" style="padding:0;overflow-x:auto">
      <table id="tokenTable">
        <thead><tr>
          <th>Model</th><th>Calls</th>
          <th>Avg ISL</th><th>p90 ISL</th><th>Max ISL</th>
          <th>Avg OSL</th><th>p90 OSL</th><th>Max OSL</th>
          <th>Total Prompt</th><th>Total Completion</th>
          <th>Total Cached</th><th>Cache Rate</th>
          <th>Avg TPS</th><th>Sys Prompt Est.</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ── EFFICIENCY ─────────────────────────────────────────────────────────── -->
<div id="tab-efficiency" class="tab-content">
  <div class="card">
    <div class="card-header">⏱💰 Latency vs Cost per Query
      <div class="card-sub">Each dot is one query. Queries in the top-right are both slow and expensive —
        highest priority for optimization. A diagonal cluster means slow queries are inherently costlier
        (more LLM calls). Outliers far from the cluster are worth investigating individually.</div>
    </div>
    <div class="card-body"><div id="latCostScatter"></div></div>
  </div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header">⚡📉 TPS vs ISL — Does Throughput Drop as Context Grows?
        <div class="card-sub">Each dot is one LLM call. A downward slope means longer prompts hurt
          inference speed (prompt-bound). A flat cloud means generation speed is independent of context
          size (compute-bound). Use this to decide whether KV-cache optimizations would help.</div>
      </div>
      <div class="card-body"><div id="tpsIslScatter"></div></div>
    </div>
    <div class="card">
      <div class="card-header">💵 Effective Cost per 1K Output Tokens by Model
        <div class="card-sub">Total spend divided by total completion tokens generated — the true output
          cost. A model with cheaper listed pricing may still be more expensive here if it generates more
          tokens to answer the same question.</div>
      </div>
      <div class="card-body"><div id="costPerKOslBar"></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-header">🎯 Model Efficiency — Output Cost vs p90 Latency
      <div class="card-sub">Each point is a model. Bottom-left is ideal: cheap output AND fast. Use this
        to compare model trade-offs when evaluating alternatives. Bubble size = total LLM call count.
      </div>
    </div>
    <div class="card-body"><div id="modelEfficiencyScatter"></div></div>
  </div>
</div>

<!-- ── PRICING ───────────────────────────────────────────────────────────── -->
<div id="tab-pricing" class="tab-content">
  <div class="grid-2">
    <div class="card">
      <div class="card-header">💵 Input Cost per 1M Tokens
        <div class="card-sub">Cost of each token sent to the model (prompt). Cheaper input pricing matters
          most for high-ISL workloads.</div>
      </div>
      <div class="card-body"><div id="pricingInputBar"></div></div>
    </div>
    <div class="card">
      <div class="card-header">💵 Output Cost per 1M Tokens
        <div class="card-sub">Cost of each token generated by the model. Output tokens are typically
          4–10× more expensive than input — high OSL workloads should use cheaper output models where
          quality allows.</div>
      </div>
      <div class="card-body"><div id="pricingOutputBar"></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-header">📋 LLM Pricing Table</div>
    <div class="card-body" style="padding:0">
      <table id="pricingTable" class="price-table">
        <thead><tr><th>Model</th><th>Input / 1M</th><th>Cached Input / 1M</th><th>Output / 1M</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <div class="card-header">🔍 Tool Pricing Table
      <div class="card-sub">Per-call charges for external APIs (search, web fetch, etc.).</div>
    </div>
    <div class="card-body" style="padding:0">
      <table id="toolPricingTable">
        <thead><tr><th>Tool</th><th>Cost per Call</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ── PER-QUERY DETAIL ──────────────────────────────────────────────────── -->
<div id="tab-detail" class="tab-content">
  <div class="card">
    <div class="card-header">📋 Per-Query Token &amp; Cost Detail</div>
    <div class="card-body" style="padding:0;overflow-x:auto">
      <table id="detailTable">
        <thead><tr>
          <th>Query #</th><th>Cost ($)</th>
          <th>Prompt (ISL)</th><th>Completion (OSL)</th><th>Cached</th>
          <th>ISL:OSL</th><th>LLM Calls</th><th>Duration (s)</th>
          <th>Question</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ── COMPARE ────────────────────────────────────────────────────────────── -->
<div id="tab-compare" class="tab-content">
  <div class="stat-grid" id="compareStats"></div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header">🤖 Cost by Model — Run A vs Run B
        <div class="card-sub">Same model appearing in both bars = same routing, different volumes or prompts.
          A model present in only one run signals a model swap between the two experiments.</div>
      </div>
      <div class="card-body"><div id="compareModelBar"></div></div>
    </div>
    <div class="card">
      <div class="card-header">🏗 Cost by Phase — Run A vs Run B
        <div class="card-sub">A phase cost shift (e.g. lower Researcher spend) often indicates fewer
          parallel search calls or a changed routing policy.</div>
      </div>
      <div class="card-body"><div id="comparePhaseBar"></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-header">📈 Per-Query Cost Delta (B − A)
      <div class="card-sub">Green bars = Run B is cheaper for that query; red bars = Run B costs more.
        Only queries present in both runs are shown — use the same filter.allowlist for both runs
        to maximise alignment.</div>
    </div>
    <div class="card-body"><div id="compareDeltaBar"></div></div>
  </div>
  <div class="card">
    <div class="card-header">📋 Per-Query Comparison Table
      <div class="card-sub">All queries from both runs. Dimmed rows = query only in one run (— in missing columns).
        Bold coloured rows = queries in both runs, with cost delta.</div>
    </div>
    <div class="card-body" style="padding:0;overflow-x:auto">
      <table id="compareTable">
        <thead><tr>
          <th>Query #</th><th>Question</th>
          <th>Cost A</th><th>Cost B</th><th>Δ Cost</th><th>Δ %</th>
          <th>ISL A</th><th>ISL B</th><th>OSL A</th><th>OSL B</th>
          <th>Dur A (s)</th><th>Dur B (s)</th>
          <th>Calls A</th><th>Calls B</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

</main>

<script>
// ── embedded data ─────────────────────────────────────────────────────────────
const DATA = __REPORT_DATA_JSON__;

// ── layout defaults ───────────────────────────────────────────────────────────
const LAYOUT_BASE = {
  paper_bgcolor: '#161b22',
  plot_bgcolor:  '#161b22',
  font: { color: '#e6edf3', size: 12, family: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' },
  margin: { t: 30, r: 20, b: 50, l: 60 },
  colorway: ['#58a6ff','#3fb950','#d29922','#bc8cff','#f85149','#39d353','#76b900','#ff7b72','#ffa657'],
  xaxis: { gridcolor: '#30363d', zerolinecolor: '#30363d' },
  yaxis: { gridcolor: '#30363d', zerolinecolor: '#30363d' },
  legend: { bgcolor: 'rgba(0,0,0,0)', bordercolor: '#30363d' },
};
const CFG = { responsive: true, displayModeBar: false };
function L(extra) { return Object.assign({}, LAYOUT_BASE, extra); }

// ── helpers ───────────────────────────────────────────────────────────────────
function fmtK(v) {
  v = +v;
  return v >= 1e6 ? (v/1e6).toFixed(2)+'M' : v >= 1e3 ? (v/1e3).toFixed(1)+'k' : String(Math.round(v));
}
function fmt$(v, d=4) { return v == null ? 'N/A' : '$' + (+v).toFixed(d); }

const PALETTE = ['#58a6ff','#3fb950','#d29922','#bc8cff','#f85149','#39d353','#76b900','#ff7b72','#ffa657'];

// ── tab switching ─────────────────────────────────────────────────────────────
let _rendered = {};
function showTab(id, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
  renderTab(id);
}
function renderTab(id) {
  if (_rendered[id]) return;
  _rendered[id] = true;
  if (id === 'overview') renderOverview();
  if (id === 'cost')     renderCost();
  if (id === 'latency')  renderLatency();
  if (id === 'tokens')     renderTokens();
  if (id === 'efficiency') renderEfficiency();
  if (id === 'pricing')    renderPricing();
  if (id === 'detail')     renderDetail();
  if (id === 'compare')    renderComparison();
}

// ── INIT ─────────────────────────────────────────────────────────────────────
document.getElementById('headerMeta').textContent =
  DATA.label + ' \u2022 ' + DATA.generated_at + ' \u2022 ' + DATA.num_queries + ' queries';
if (DATA.comparison) {
  document.getElementById('compareBtn').style.display = '';
}

// ── OVERVIEW ─────────────────────────────────────────────────────────────────
function renderOverview() {
  const d = DATA;
  const cr = d.total_prompt_tokens > 0
    ? (d.total_cached_tokens / d.total_prompt_tokens * 100).toFixed(1) : '0';
  document.getElementById('overviewStats').innerHTML = `
    <div class="stat blue"><div class="label">Queries</div>
      <div class="value">${d.num_queries}</div></div>
    <div class="stat orange"><div class="label">Total Cost</div>
      <div class="value">${fmt$(d.total_cost_usd,2)}</div>
      <div class="sub">${fmt$(d.avg_cost_usd,4)}/query avg</div></div>
    <div class="stat orange"><div class="label">LLM Cost</div>
      <div class="value">${fmt$(d.llm_cost_usd,2)}</div>
      <div class="sub">token charges</div></div>
    <div class="stat orange"><div class="label">Tool API Cost</div>
      <div class="value">${fmt$(d.tool_cost_usd,2)}</div>
      <div class="sub">search / external APIs</div></div>
    <div class="stat green"><div class="label">Cache Savings</div>
      <div class="value">${fmt$(d.cache_savings_usd,2)}</div>
      <div class="sub">${cr}% cache rate</div></div>
    <div class="stat orange"><div class="label">Total Prompt</div>
      <div class="value">${fmtK(d.total_prompt_tokens)}</div>
      <div class="sub">ISL tokens</div></div>
    <div class="stat blue"><div class="label">Total Completion</div>
      <div class="value">${fmtK(d.total_completion_tokens)}</div>
      <div class="sub">OSL tokens</div></div>
    <div class="stat purple"><div class="label">Total LLM Calls</div>
      <div class="value">${d.total_llm_calls}</div></div>
  `;

  // Cost by model bar
  const mods = Object.keys(d.by_model).filter(m => d.by_model[m] > 0.0001);
  Plotly.newPlot('overviewModelBar', [{
    type: 'bar', x: mods, y: mods.map(m => d.by_model[m]),
    text: mods.map(m => fmt$(d.by_model[m],3)), textposition: 'outside',
    marker: { color: PALETTE },
  }], L({ height: 280, yaxis: {title:'Cost (USD)'}, xaxis: {automargin:true,tickangle:-25},
           margin: {t:20,r:20,b:90,l:70}, showlegend: false }), CFG);

  // Cost by phase horizontal bar
  const phases = Object.keys(d.by_phase);
  Plotly.newPlot('overviewPhaseBar', [{
    type: 'bar', orientation: 'h',
    y: phases, x: phases.map(p => d.by_phase[p]),
    text: phases.map(p => fmt$(d.by_phase[p],3)), textposition: 'outside',
    marker: { color: '#bc8cff' },
  }], L({ height: 280, xaxis: {title:'Cost (USD)'}, yaxis: {automargin:true},
           margin: {t:20,r:80,b:50,l:140} }), CFG);

  // Per-query table
  const tbody = document.querySelector('#overviewTable tbody');
  tbody.innerHTML = d.per_query.map(q => {
    const cr2 = q.input_tokens > 0 ? (q.cached_tokens/q.input_tokens*100).toFixed(1)+'%' : '—';
    return `<tr>
      <td><strong>${q.id}</strong></td>
      <td style="color:#d29922">${fmt$(q.cost_usd)}</td>
      <td>${(q.input_tokens||0).toLocaleString()}</td>
      <td>${(q.output_tokens||0).toLocaleString()}</td>
      <td style="color:#39d353">${(q.cached_tokens||0).toLocaleString()}</td>
      <td style="color:#39d353">${cr2}</td>
      <td>${q.entry_count||0}</td>
      <td>${(q.duration_s||0).toFixed(1)}</td>
    </tr>`;
  }).join('');
}

// ── COST ─────────────────────────────────────────────────────────────────────
function renderCost() {
  const d = DATA;
  const mods = Object.keys(d.by_model).filter(m => d.by_model[m] > 0.0001);

  // Donut by model
  Plotly.newPlot('costPie', [{
    type: 'pie', labels: mods, values: mods.map(m => d.by_model[m]),
    hole: .45, textfont: { color: '#e6edf3' },
    marker: { colors: PALETTE },
  }], L({ height: 320, showlegend: true, margin: {t:20,r:120,b:20,l:20} }), CFG);

  // Horizontal bar by phase
  const phases = Object.keys(d.by_phase);
  Plotly.newPlot('costPhaseBar', [{
    type: 'bar', orientation: 'h',
    y: phases, x: phases.map(p => d.by_phase[p]),
    text: phases.map(p => fmt$(d.by_phase[p],3)), textposition: 'outside',
    marker: { color: '#bc8cff' },
  }], L({ height: 320, xaxis:{title:'Cost (USD)'}, yaxis:{automargin:true},
           margin:{t:20,r:80,b:50,l:140} }), CFG);

  // Tool cost bar
  const toolData = d.by_tool || {};
  const toolCard = document.getElementById('toolCostCard');
  const toolNames = Object.keys(toolData).filter(t => toolData[t].total_cost_usd > 0 || toolData[t].calls > 0);
  if (toolNames.length > 0) {
    const toolCosts = toolNames.map(t => toolData[t].total_cost_usd);
    const toolCalls = toolNames.map(t => toolData[t].calls);
    const hasCost = toolCosts.some(c => c > 0);
    if (hasCost) {
      Plotly.newPlot('toolCostBar', [{
        type: 'bar', x: toolNames, y: toolCosts,
        text: toolNames.map((t,i) => fmt$(toolCosts[i],3) + ' (' + toolCalls[i] + ' calls)'),
        textposition: 'outside',
        marker: { color: '#39d353' },
      }], L({ height: 280, yaxis:{title:'Cost (USD)'}, xaxis:{automargin:true,tickangle:-25},
              margin:{t:20,r:20,b:90,l:70}, showlegend:false }), CFG);
    } else {
      // Show call counts even when all costs are $0 (tools not priced)
      Plotly.newPlot('toolCostBar', [{
        type: 'bar', x: toolNames, y: toolCalls,
        text: toolCalls.map(c => c + ' calls'), textposition: 'outside',
        marker: { color: '#58a6ff' },
      }], L({ height: 280, yaxis:{title:'Call Count'}, xaxis:{automargin:true,tickangle:-25},
              margin:{t:20,r:20,b:90,l:70}, showlegend:false }), CFG);
      if (toolCard) {
        const sub = toolCard.querySelector('.card-sub');
        if (sub) {
          sub.textContent =
            'Tool call counts shown (no cost data — add tool prices to '
            + 'tokenomics.pricing.tools in the config to see cost breakdown).';
        }
      }
    }
  } else {
    if (toolCard) toolCard.style.display = 'none';
  }

  // Histogram: per-query cost — only useful with enough data points
  const MIN_HIST = 10;
  const histCard = document.getElementById('costHistogramCard');
  if (d.num_queries >= MIN_HIST) {
    const costs = d.per_query.map(q => q.cost_usd).filter(v => v > 0);
    Plotly.newPlot('costHistogram', [{
      type: 'histogram', x: costs, nbinsx: Math.min(30, Math.max(5, costs.length)),
      marker: { color: '#d29922', opacity: .85 },
    }], L({ height: 250, xaxis:{title:'Cost per query (USD)'}, yaxis:{title:'Count'},
             margin:{t:20,r:20,b:50,l:60}, showlegend:false }), CFG);
  } else {
    if (histCard) histCard.style.display = 'none';
  }

  // Stacked bar: cost by phase per query
  const phaseColors = { Orchestrator: '#58a6ff', Planner: '#bc8cff', Researcher: '#3fb950' };
  const stackTraces = (d.phase_order||[]).map(ph => ({
    type: 'bar', name: ph,
    x: d.per_query.map(q => 'Q' + q.id),
    y: d.per_query.map(q => (q.by_phase||{})[ph]||0),
    marker: { color: phaseColors[ph]||'#8b949e' },
  }));
  Plotly.newPlot('costPerQueryStack', stackTraces,
    L({ height: 300, barmode: 'stack', yaxis:{title:'Cost (USD)'},
        xaxis:{automargin:true,tickangle:-25}, margin:{t:20,r:20,b:90,l:70} }), CFG);
}

// ── LATENCY ──────────────────────────────────────────────────────────────────
function renderLatency() {
  const d = DATA;

  // LLM percentile bars
  const llmE = Object.entries(d.llm_latency||{}).sort((a,b) => b[1].p90_ms - a[1].p90_ms);
  if (llmE.length) {
    const names = llmE.map(e => e[0]);
    Plotly.newPlot('llmLatencyBar', [
      { type:'bar', name:'p50', x:names, y:llmE.map(e=>e[1].p50_ms/1000), marker:{color:'#3fb950'} },
      { type:'bar', name:'p90', x:names, y:llmE.map(e=>e[1].p90_ms/1000), marker:{color:'#58a6ff'} },
      { type:'bar', name:'p99', x:names, y:llmE.map(e=>e[1].p99_ms/1000), marker:{color:'#f85149'} },
    ], L({ height:320, barmode:'group', yaxis:{title:'Seconds'}, xaxis:{automargin:true,tickangle:-30},
           margin:{t:20,r:20,b:100,l:60} }), CFG);
  } else {
    document.getElementById('llmLatencyBar').innerHTML =
      '<p style="padding:40px;color:var(--muted);text-align:center">'
      + 'No LLM latency data (missing span_event_timestamp?)</p>';
  }

  // Tool percentile bars (skip near-zero tools)
  const toolE = Object.entries(d.tool_latency||{})
    .filter(([k,v]) => v.p90_ms > 10)
    .sort((a,b) => b[1].p90_ms - a[1].p90_ms)
    .slice(0, 12);
  if (toolE.length) {
    const tnames = toolE.map(e => e[0]);
    Plotly.newPlot('toolLatencyBar', [
      { type:'bar', name:'p50', x:tnames, y:toolE.map(e=>e[1].p50_ms/1000), marker:{color:'#3fb950'} },
      { type:'bar', name:'p90', x:tnames, y:toolE.map(e=>e[1].p90_ms/1000), marker:{color:'#58a6ff'} },
      { type:'bar', name:'p99', x:tnames, y:toolE.map(e=>e[1].p99_ms/1000), marker:{color:'#f85149'} },
    ], L({ height:320, barmode:'group', yaxis:{title:'Seconds'}, xaxis:{automargin:true,tickangle:-30},
           margin:{t:20,r:20,b:100,l:60} }), CFG);
  } else {
    document.getElementById('toolLatencyBar').innerHTML =
      '<p style="padding:40px;color:var(--muted);text-align:center">No significant tool latency data</p>';
  }

}


// ── TOKENS ───────────────────────────────────────────────────────────────────
function renderTokens() {
  const ts  = DATA.token_stats || {};
  const bm  = ts.by_model || {};
  const bc  = ts.by_component || {};
  const spl = ts.isl_latency_sample || [];
  const grw = ts.isl_growth || {};
  const sys = ts.sys_prompt_est || {};

  const models = Object.keys(bm);
  const colorOf = m => PALETTE[models.indexOf(m) % PALETTE.length];

  // Stat grid
  const totalPrompt = models.reduce((s,m) => s + (bm[m].total_isl||0), 0);
  const totalComp   = models.reduce((s,m) => s + (bm[m].total_osl||0), 0);
  const totalCached = models.reduce((s,m) => s + (bm[m].total_cached||0), 0);
  const totalCalls  = models.reduce((s,m) => s + (bm[m].calls||0), 0);
  const cacheRate   = totalPrompt > 0 ? (totalCached/totalPrompt*100).toFixed(1) : '0';
  document.getElementById('tokenStats').innerHTML = `
    <div class="stat blue"><div class="label">Total LLM Calls</div>
      <div class="value">${fmtK(totalCalls)}</div></div>
    <div class="stat orange"><div class="label">Total Prompt</div>
      <div class="value">${fmtK(totalPrompt)}</div>
      <div class="sub">ISL tokens</div></div>
    <div class="stat green"><div class="label">Total Completion</div>
      <div class="value">${fmtK(totalComp)}</div>
      <div class="sub">OSL tokens</div></div>
    <div class="stat purple"><div class="label">Total Cached</div>
      <div class="value">${fmtK(totalCached)}</div>
      <div class="sub">${cacheRate}% cache rate</div></div>
    <div class="stat blue"><div class="label">ISL:OSL Ratio</div>
      <div class="value">${totalComp > 0 ? (totalPrompt/totalComp).toFixed(1) : '—'}:1</div></div>
  `;

  // ISL p50/p90/p99 by model
  Plotly.newPlot('islBar', [
    { type:'bar', name:'p50', x:models, y:models.map(m=>bm[m].isl_p50||0), marker:{color:'#3fb950'} },
    { type:'bar', name:'p90', x:models, y:models.map(m=>bm[m].isl_p90||0), marker:{color:'#58a6ff'} },
    { type:'bar', name:'p99', x:models, y:models.map(m=>bm[m].isl_p99||0), marker:{color:'#f85149'} },
  ], L({ height:300, barmode:'group', yaxis:{title:'Tokens'}, xaxis:{automargin:true,tickangle:-25},
    margin:{t:20,r:20,b:90,l:70},
    annotations: models.map(m => ({
      x:m, y:bm[m].isl_max||0, text:'max '+fmtK(bm[m].isl_max||0),
      showarrow:false, font:{size:9,color:'#8b949e'}, yshift:4,
    }))
  }), CFG);

  // OSL p50/p90/p99 by model
  Plotly.newPlot('oslBar', [
    { type:'bar', name:'p50', x:models, y:models.map(m=>bm[m].osl_p50||0), marker:{color:'#3fb950'} },
    { type:'bar', name:'p90', x:models, y:models.map(m=>bm[m].osl_p90||0), marker:{color:'#58a6ff'} },
    { type:'bar', name:'p99', x:models, y:models.map(m=>bm[m].osl_p99||0), marker:{color:'#f85149'} },
  ], L({ height:300, barmode:'group', yaxis:{title:'Tokens'}, xaxis:{automargin:true,tickangle:-25},
    margin:{t:20,r:20,b:90,l:70} }), CFG);

  // ISL growth (context accumulation)
  const growthTraces = Object.entries(grw).map(([model, pts], i) => ({
    type:'scatter', mode:'lines+markers', name: model,
    x: pts.map(p=>p.idx), y: pts.map(p=>p.avg_isl),
    line: { color: colorOf(model), width: 2 },
    marker: { size: 5, color: colorOf(model) },
    hovertemplate: model + '<br>Call #%{x}<br>Avg ISL: %{y:,.0f} tokens<extra></extra>',
  }));
  // Dashed sys-prompt estimate lines
  Object.entries(sys).forEach(([model, minIsl], i) => {
    const maxIdx = Math.max(...((grw[model]||[{idx:0}]).map(p=>p.idx)), 10);
    growthTraces.push({
      type:'scatter', mode:'lines', name: model+' sys-prompt est.',
      x: [0, maxIdx], y: [minIsl, minIsl],
      line: { color: colorOf(model), width: 1, dash: 'dot' },
      hovertemplate: 'Sys-prompt lower bound: ' + fmtK(minIsl) + ' tokens<extra></extra>',
    });
  });
  Plotly.newPlot('islGrowth', growthTraces,
    L({ height:320, xaxis:{title:'Call index within query', dtick:5}, yaxis:{title:'Avg ISL (tokens)'},
        margin:{t:20,r:20,b:60,l:80},
        annotations:[{text:'Dashed = system-prompt lower bound (min ISL observed)',
          x:0.01, y:0.97, xref:'paper', yref:'paper', showarrow:false,
          font:{color:'#8b949e',size:10}}]
    }), CFG);

  // TPS bar
  const tpsSorted = models.map(m=>({m, tps:bm[m].tps_mean||0})).sort((a,b)=>b.tps-a.tps);
  Plotly.newPlot('tpsBar', [{
    type:'bar', x:tpsSorted.map(d=>d.m), y:tpsSorted.map(d=>d.tps),
    text:tpsSorted.map(d=>d.tps.toFixed(1)+' tok/s'), textposition:'outside',
    marker:{color: tpsSorted.map((_,i) => PALETTE[i%PALETTE.length])},
  }], L({ height:300, yaxis:{title:'Completion tokens / second'},
    xaxis:{automargin:true,tickangle:-25}, margin:{t:20,r:20,b:90,l:70}, showlegend:false }), CFG);

  // Cache breakdown stacked bar
  Plotly.newPlot('cacheBreakdown', [
    {
      type:'bar', name:'Cached prompt', x:models,
      y:models.map(m=>bm[m].total_cached||0), marker:{color:'#39d353'},
    },
    {
      type:'bar', name:'Uncached prompt', x:models,
      y:models.map(m=>(bm[m].total_isl||0)-(bm[m].total_cached||0)),
      marker:{color:'#30363d'},
    },
    {
      type:'bar', name:'Completion', x:models,
      y:models.map(m=>bm[m].total_osl||0), marker:{color:'#58a6ff'},
    },
  ], L({ height:320, barmode:'stack', yaxis:{title:'Tokens'},
    xaxis:{automargin:true,tickangle:-25}, margin:{t:20,r:20,b:90,l:80} }), CFG);

  // ISL vs Latency scatter
  const modelsSeen = [...new Set(spl.map(p=>p.model))];
  const scatterTraces = modelsSeen.map(m => {
    const pts = spl.filter(p=>p.model===m);
    return {
      type:'scatter', mode:'markers', name:m,
      x: pts.map(p=>p.isl), y: pts.map(p=>p.dur_s),
      marker: { color: colorOf(m), size: 5, opacity: .55 },
      hovertemplate: 'ISL: %{x:,}<br>Latency: %{y:.2f}s<extra>'+m+'</extra>',
    };
  });
  Plotly.newPlot('islLatencyScatter', scatterTraces,
    L({ height:320, xaxis:{title:'Prompt tokens (ISL)'}, yaxis:{title:'Latency (s)'},
        margin:{t:20,r:20,b:60,l:70} }), CFG);

  // Component token stacked bar (by phase)
  const comps = Object.keys(bc);
  Plotly.newPlot('componentTokenStack', [
    {
      type:'bar', name:'Prompt (uncached)', x:comps,
      y:comps.map(c=>(bc[c].total_isl||0)-(bc[c].total_cached||0)),
      marker:{color:'#30363d'},
    },
    {
      type:'bar', name:'Prompt (cached)', x:comps,
      y:comps.map(c=>bc[c].total_cached||0), marker:{color:'#39d353'},
    },
    {
      type:'bar', name:'Completion', x:comps,
      y:comps.map(c=>bc[c].total_osl||0), marker:{color:'#58a6ff'},
    },
    {
      type:'bar', name:'Reasoning', x:comps,
      y:comps.map(c=>bc[c].total_reasoning||0), marker:{color:'#bc8cff'},
    },
  ], L({ height:320, barmode:'stack', yaxis:{title:'Tokens'},
    xaxis:{automargin:true,tickangle:-25}, margin:{t:20,r:20,b:90,l:80} }), CFG);

  // Predicted vs Actual OSL scatter
  const pva = ts.predicted_vs_actual || [];
  const predCard = document.getElementById('predVsActualCard');
  // Hide when all predicted == actual (post-hoc filled, no predictive signal)
  const hasRealPredictions = pva.some(p => p.predicted !== p.actual);
  if (pva.length === 0 || !hasRealPredictions) {
    if (predCard) predCard.style.display = 'none';
  } else {
    const pvaModels = [...new Set(pva.map(p => p.model))];
    const pvaTraces = pvaModels.map(m => {
      const pts = pva.filter(p => p.model === m);
      const errs = pts.map(p => p.actual - p.predicted);
      const pct = pts.map(p => p.predicted > 0 ? ((p.actual - p.predicted) / p.predicted * 100) : 0);
      return {
        type: 'scatter', mode: 'markers', name: m,
        x: pts.map(p => p.predicted), y: pts.map(p => p.actual),
        customdata: pts.map((p, i) => [errs[i], pct[i].toFixed(1)]),
        marker: { color: colorOf(m), size: 5, opacity: .65 },
        hovertemplate:
          'Predicted: %{x:,}<br>Actual: %{y:,}<br>Error: %{customdata[0]:+,} '
          + '(%{customdata[1]}%)<extra>' + m + '</extra>',
      };
    });
    // Perfect-prediction diagonal
    const allVals = pva.flatMap(p => [p.predicted, p.actual]);
    const axMax = Math.max(...allVals) * 1.05;
    pvaTraces.push({
      type: 'scatter', mode: 'lines', name: 'Perfect prediction',
      x: [0, axMax], y: [0, axMax],
      line: { color: '#8b949e', width: 1, dash: 'dot' },
      hoverinfo: 'skip',
    });
    Plotly.newPlot('predVsActualScatter', pvaTraces,
      L({ height: 360, xaxis: {title: 'NOVA Predicted OSL (tokens)', range: [0, axMax]},
          yaxis: {title: 'Actual OSL (tokens)', range: [0, axMax]},
          margin: {t:20,r:20,b:60,l:80} }), CFG);
  }

  // Token summary table
  const tbody = document.querySelector('#tokenTable tbody');
  tbody.innerHTML = models.map(m => {
    const s = bm[m];
    const est = sys[m];
    return `<tr>
      <td><strong>${m}</strong></td>
      <td>${(s.calls||0).toLocaleString()}</td>
      <td>${fmtK(s.isl_mean||0)}</td>
      <td style="color:#58a6ff">${fmtK(s.isl_p90||0)}</td>
      <td style="color:#f85149">${fmtK(s.isl_max||0)}</td>
      <td>${fmtK(s.osl_mean||0)}</td>
      <td style="color:#58a6ff">${fmtK(s.osl_p90||0)}</td>
      <td style="color:#f85149">${fmtK(s.osl_max||0)}</td>
      <td style="color:#8b949e">${fmtK(s.total_isl||0)}</td>
      <td style="color:#8b949e">${fmtK(s.total_osl||0)}</td>
      <td style="color:#39d353">${fmtK(s.total_cached||0)}</td>
      <td style="color:#39d353">${((s.cache_rate||0)*100).toFixed(1)}%</td>
      <td>${(s.tps_mean||0).toFixed(1)} tok/s</td>
      <td style="color:#d29922;font-style:italic"
        title="Min ISL observed — lower bound on system-prompt size">~${
        est != null ? fmtK(est) : 'N/A'}</td>
    </tr>`;
  }).join('');
}

// ── EFFICIENCY ────────────────────────────────────────────────────────────────
function renderEfficiency() {
  const d = DATA;
  const bm = (d.token_stats || {}).by_model || {};
  const ll = d.llm_latency || {};
  const spl = (d.token_stats || {}).isl_latency_sample || [];
  const models = Object.keys(bm);

  // ── Per-query latency vs cost scatter ──
  const pq = d.per_query || [];
  const costs = pq.map(q => q.cost_usd || 0);
  const durs  = pq.map(q => q.duration_s || 0);
  const maxCost = Math.max(...costs);
  Plotly.newPlot('latCostScatter', [{
    type: 'scatter', mode: 'markers+text',
    x: durs, y: costs,
    text: pq.map(q => 'Q' + q.id),
    textposition: 'top center',
    textfont: { size: 10, color: '#8b949e' },
    marker: {
      color: costs,
      colorscale: 'Viridis',
      size: 10, opacity: .8,
      colorbar: { title: 'Cost ($)', thickness: 12, len: .7 },
    },
    hovertemplate: 'Query %{text}<br>Duration: %{x:.1f}s<br>Cost: $%{y:.4f}<extra></extra>',
  }], L({ height: 380, xaxis: {title: 'Workflow duration (s)'},
          yaxis: {title: 'Total cost (USD)'},
          margin: {t:20,r:80,b:60,l:70}, showlegend: false }), CFG);

  // ── TPS vs ISL scatter (from isl_latency_sample) ──
  const modelsSeen = [...new Set(spl.map(p => p.model))];
  const tpsIslTraces = modelsSeen.map(m => {
    const pts = spl.filter(p => p.model === m && p.dur_s > 0 && p.osl > 0);
    return {
      type: 'scatter', mode: 'markers', name: m,
      x: pts.map(p => p.isl),
      y: pts.map(p => p.osl / p.dur_s),
      marker: { color: PALETTE[models.indexOf(m) % PALETTE.length], size: 5, opacity: .55 },
      hovertemplate: 'ISL: %{x:,}<br>TPS: %{y:.1f}<extra>' + m + '</extra>',
    };
  });
  Plotly.newPlot('tpsIslScatter', tpsIslTraces,
    L({ height: 340, xaxis: {title: 'Prompt tokens (ISL)'},
        yaxis: {title: 'Completion tokens / second (TPS)'},
        margin: {t:20,r:20,b:60,l:70} }), CFG);

  // ── Effective cost per 1K output tokens ──
  const cpk = models.map(m => ({
    m,
    val: bm[m].total_osl > 0 ? (d.by_model[m] || 0) / (bm[m].total_osl / 1000) : 0,
  })).sort((a, b) => b.val - a.val);
  Plotly.newPlot('costPerKOslBar', [{
    type: 'bar', x: cpk.map(d => d.m), y: cpk.map(d => d.val),
    text: cpk.map(d => '$' + d.val.toFixed(4)), textposition: 'outside',
    marker: { color: cpk.map((_, i) => PALETTE[i % PALETTE.length]) },
  }], L({ height: 300, yaxis: {title: '$ per 1K completion tokens'},
          xaxis: {automargin: true, tickangle: -25},
          margin: {t:20,r:20,b:90,l:80}, showlegend: false }), CFG);

  // ── Model efficiency: output cost vs p90 latency bubble ──
  const effModels = models.filter(m => bm[m].total_osl > 0 && ll[m]);
  if (effModels.length > 0) {
    const cpkMap = Object.fromEntries(cpk.map(d => [d.m, d.val]));
    Plotly.newPlot('modelEfficiencyScatter', [{
      type: 'scatter', mode: 'markers+text',
      x: effModels.map(m => (ll[m].p90_ms || 0) / 1000),
      y: effModels.map(m => cpkMap[m] || 0),
      text: effModels.map(m => m.split('/').pop()),
      textposition: 'top center',
      textfont: { size: 11 },
      marker: {
        size: effModels.map(m => Math.max(14, Math.min(50, (bm[m].calls || 0) / 5))),
        color: effModels.map((_, i) => PALETTE[i % PALETTE.length]),
        opacity: .8, line: {width: 1, color: '#30363d'},
      },
      hovertemplate: effModels.map(m =>
        '<b>' + m + '</b><br>p90 latency: ' + ((ll[m].p90_ms||0)/1000).toFixed(1) + 's<br>' +
        'Cost/1K out: $' + (cpkMap[m]||0).toFixed(4) + '<br>Calls: ' + (bm[m].calls||0) + '<extra></extra>'),
    }], L({ height: 380, xaxis: {title: 'p90 LLM latency (s)'},
            yaxis: {title: '$ per 1K completion tokens'},
            margin: {t:20,r:20,b:60,l:80}, showlegend: false,
            annotations: [{text: 'Bubble size = call count. Bottom-left = cheapest + fastest.',
              x: .01, y: .99, xref: 'paper', yref: 'paper', showarrow: false,
              font: {color: '#8b949e', size: 10}}] }), CFG);
  } else {
    document.getElementById('modelEfficiencyScatter').innerHTML =
      '<p style="padding:40px;color:var(--muted);text-align:center">Not enough model diversity for comparison</p>';
  }
}

// ── PRICING ───────────────────────────────────────────────────────────────────
function renderPricing() {
  const p = DATA.pricing_snapshot || {};
  const mods = Object.keys(p).filter(m => m !== 'default' && p[m].input_per_1m_tokens > 0);

  Plotly.newPlot('pricingInputBar', [{
    type:'bar', x:mods, y:mods.map(m=>p[m].input_per_1m_tokens),
    text:mods.map(m=>'$'+p[m].input_per_1m_tokens.toFixed(3)), textposition:'outside',
    marker:{color:'#58a6ff'},
  }], L({ height:300, yaxis:{title:'$/1M tokens'}, xaxis:{automargin:true,tickangle:-35},
          margin:{t:20,r:20,b:120,l:60}, showlegend:false }), CFG);

  Plotly.newPlot('pricingOutputBar', [{
    type:'bar', x:mods, y:mods.map(m=>p[m].output_per_1m_tokens),
    text:mods.map(m=>'$'+p[m].output_per_1m_tokens.toFixed(3)), textposition:'outside',
    marker:{color:'#d29922'},
  }], L({ height:300, yaxis:{title:'$/1M tokens'}, xaxis:{automargin:true,tickangle:-35},
          margin:{t:20,r:20,b:120,l:60}, showlegend:false }), CFG);

  const tbody = document.querySelector('#pricingTable tbody');
  tbody.innerHTML = Object.keys(p).map(m => {
    const pr = p[m];
    const cachedIn = pr.cached_input_per_1m_tokens;
    const cacheDiscount = cachedIn != null && cachedIn < pr.input_per_1m_tokens
      ? '$' + cachedIn.toFixed(3) + '/1M'
      : '—';
    return `<tr>
      <td>${m}</td>
      <td>$${pr.input_per_1m_tokens.toFixed(3)}/1M</td>
      <td>${cacheDiscount}</td>
      <td>$${pr.output_per_1m_tokens.toFixed(3)}/1M</td>
    </tr>`;
  }).join('');

  // Tool pricing table
  const tp = DATA.tool_pricing_snapshot || {};
  const toolTbody = document.querySelector('#toolPricingTable tbody');
  if (toolTbody) {
    const toolKeys = Object.keys(tp);
    if (toolKeys.length > 0) {
      toolTbody.innerHTML = toolKeys.map(t =>
        `<tr><td>${t}</td><td style="color:#3fb950;font-family:monospace">$${(+tp[t]).toFixed(4)}/call</td></tr>`
      ).join('');
    } else {
      toolTbody.innerHTML =
        '<tr><td colspan="2" style="color:#8b949e">No tool pricing configured. '
        + 'Add a <code>tools:</code> section under <code>tokenomics.pricing</code> '
        + 'in the config YAML.</td></tr>';
    }
  }
}

// ── PER-QUERY DETAIL ──────────────────────────────────────────────────────────
function renderDetail() {
  const tbody = document.querySelector('#detailTable tbody');
  tbody.innerHTML = DATA.per_query.map(q => {
    const isl = q.input_tokens||0, osl = q.output_tokens||0;
    const ratio = osl > 0 ? (isl/osl).toFixed(1)+':1' : '—';
    const qtxt = q.question ? q.question.substring(0,120)+(q.question.length>120?'\u2026':'') : '—';
    return `<tr>
      <td><strong>${q.id}</strong></td>
      <td style="color:#d29922">${fmt$(q.cost_usd)}</td>
      <td>${isl.toLocaleString()}</td>
      <td>${osl.toLocaleString()}</td>
      <td style="color:#39d353">${(q.cached_tokens||0).toLocaleString()}</td>
      <td>${ratio}</td>
      <td>${q.entry_count||0}</td>
      <td>${(q.duration_s||0).toFixed(1)}</td>
      <td style="color:#8b949e;max-width:400px;word-break:break-word">${qtxt}</td>
    </tr>`;
  }).join('');
}

// ── COMPARE ───────────────────────────────────────────────────────────────────
function renderComparison() {
  const cmp = DATA.comparison;
  if (!cmp) return;

  const costSaved  = -cmp.cost_delta;
  const savingsPct = -cmp.cost_pct_change;
  const callsDelta = cmp.total_llm_calls_b - cmp.total_llm_calls_a;
  const ds = v => (v >= 0 ? '+' : '') + v;

  document.getElementById('compareStats').innerHTML = `
    <div class="stat orange"><div class="label">Run A Total Cost</div>
      <div class="value">${fmt$(cmp.total_cost_a,2)}</div>
      <div class="sub">${cmp.label_a}</div></div>
    <div class="stat orange"><div class="label">Run B Total Cost</div>
      <div class="value">${fmt$(cmp.total_cost_b,2)}</div>
      <div class="sub">${cmp.label_b}</div></div>
    <div class="stat ${costSaved>=0?'green':'red'}"><div class="label">Cost Delta (B \u2212 A)</div>
      <div class="value">${costSaved>=0?'\u2212':'+'}${fmt$(Math.abs(cmp.cost_delta),2)}</div>
      <div class="sub">${
        savingsPct>=0?savingsPct.toFixed(1)+'% cheaper':(-savingsPct).toFixed(1)+'% costlier'
      }</div></div>
    <div class="stat blue"><div class="label">Aligned / A / B</div>
      <div class="value">${cmp.num_common_queries}</div>
      <div class="sub">of ${cmp.num_queries_a} A &amp; ${cmp.num_queries_b} B</div></div>
    <div class="stat purple"><div class="label">LLM Calls A \u2192 B</div>
      <div class="value">${cmp.total_llm_calls_a} \u2192 ${cmp.total_llm_calls_b}</div>
      <div class="sub">${ds(callsDelta)} calls</div></div>
    <div class="stat green"><div class="label">Cache Rate A / B</div>
      <div class="value">${(cmp.cache_rate_a*100).toFixed(1)}% / ${(cmp.cache_rate_b*100).toFixed(1)}%</div></div>
  `;

  // Cost by model grouped bar
  const allMods = [...new Set([...Object.keys(cmp.by_model_a||{}), ...Object.keys(cmp.by_model_b||{})])];
  const filtMods = allMods.filter(m => (cmp.by_model_a[m]||0) > 0.0001 || (cmp.by_model_b[m]||0) > 0.0001);
  Plotly.newPlot('compareModelBar', [
    { type:'bar', name:cmp.label_a, x:filtMods, y:filtMods.map(m=>cmp.by_model_a[m]||0), marker:{color:'#58a6ff'} },
    { type:'bar', name:cmp.label_b, x:filtMods, y:filtMods.map(m=>cmp.by_model_b[m]||0), marker:{color:'#3fb950'} },
  ], L({ height:300, barmode:'group', yaxis:{title:'Cost (USD)'},
         xaxis:{automargin:true,tickangle:-25}, margin:{t:20,r:20,b:90,l:70} }), CFG);

  // Cost by phase grouped bar
  const allPhs = [...new Set([...Object.keys(cmp.by_phase_a||{}), ...Object.keys(cmp.by_phase_b||{})])];
  Plotly.newPlot('comparePhaseBar', [
    { type:'bar', name:cmp.label_a, x:allPhs, y:allPhs.map(p=>cmp.by_phase_a[p]||0), marker:{color:'#58a6ff'} },
    { type:'bar', name:cmp.label_b, x:allPhs, y:allPhs.map(p=>cmp.by_phase_b[p]||0), marker:{color:'#3fb950'} },
  ], L({ height:300, barmode:'group', yaxis:{title:'Cost (USD)'},
         xaxis:{automargin:true,tickangle:-25}, margin:{t:20,r:20,b:90,l:70} }), CFG);

  // Per-query delta bar — only queries present in BOTH runs
  const pq     = cmp.per_query || [];
  const pqBoth = pq.filter(q => q.in_both);
  if (pqBoth.length) {
    Plotly.newPlot('compareDeltaBar', [{
      type:'bar', x:pqBoth.map(q=>'Q'+q.id), y:pqBoth.map(q=>q.cost_delta),
      text:pqBoth.map(q=>(q.cost_delta<=0?'':'+')+'$'+(+q.cost_delta).toFixed(4)),
      textposition:'outside',
      marker:{ color:pqBoth.map(q=>q.cost_delta<=0?'#3fb950':'#f85149') },
      hovertemplate:'Q%{x}: $%{y:.4f}<extra></extra>',
    }], L({ height:320,
            yaxis:{title:'Cost delta: B \u2212 A (USD)', zerolinecolor:'#8b949e', zeroline:true},
            xaxis:{automargin:true, tickangle:-45},
            margin:{t:20,r:20,b:110,l:70}, showlegend:false }), CFG);
  } else {
    document.getElementById('compareDeltaBar').innerHTML =
      '<p style="padding:40px;color:var(--muted);text-align:center">No queries aligned between the two runs — '
      + 'use the same filter.allowlist for both runs.</p>';
  }

  // Comparison table — full union: null values shown as em-dash
  const fmt$N  = v => v == null ? '\u2014' : fmt$(v);
  const fmtKN  = v => v == null ? '\u2014' : fmtK(v);
  const fmtTN  = v => v == null ? '\u2014' : (+v).toFixed(1);
  const fmtCN  = v => v == null ? '\u2014' : String(v);
  const tbody  = document.querySelector('#compareTable tbody');
  tbody.innerHTML = pq.map(q => {
    const hasBoth = q.in_both;
    const dc   = !hasBoth ? '#8b949e' : (q.cost_delta <= 0 ? '#3fb950' : '#f85149');
    const dTxt = !hasBoth ? '\u2014'
               : (q.cost_delta<0?'\u2212':q.cost_delta>0?'+':'')+'$'+Math.abs(q.cost_delta).toFixed(4);
    const pStr = !hasBoth ? '\u2014'
               : (q.cost_pct<=0?'':'+') + q.cost_pct.toFixed(1) + '%';
    const qtxt = (q.question||'').substring(0,80) + (q.question&&q.question.length>80?'\u2026':'');
    const rowStyle = !hasBoth ? ' style="opacity:.65"' : '';
    return `<tr${rowStyle}>
      <td><strong>${q.id}</strong></td>
      <td style="color:#8b949e;max-width:200px;word-break:break-word;font-size:12px">${qtxt||'\u2014'}</td>
      <td style="color:#d29922">${fmt$N(q.cost_a)}</td>
      <td style="color:#d29922">${fmt$N(q.cost_b)}</td>
      <td style="color:${dc};font-weight:600">${dTxt}</td>
      <td style="color:${dc}">${pStr}</td>
      <td>${fmtKN(q.isl_a)}</td>
      <td>${fmtKN(q.isl_b)}</td>
      <td>${fmtKN(q.osl_a)}</td>
      <td>${fmtKN(q.osl_b)}</td>
      <td>${fmtTN(q.duration_a)}</td>
      <td>${fmtTN(q.duration_b)}</td>
      <td>${fmtCN(q.llm_calls_a)}</td>
      <td>${fmtCN(q.llm_calls_b)}</td>
    </tr>`;
  }).join('');
}

// ── INITIAL RENDER ────────────────────────────────────────────────────────────
renderTab('overview');
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def render_html(report_data: dict) -> str:
    return _HTML.replace("__REPORT_DATA_JSON__", json.dumps(report_data, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_report(
    trace_path: str | list[str],
    config_path: str,
    output_path: str | None = None,
) -> str:
    """Generate a tokenomics HTML report.

    Parameters
    ----------
    trace_path:
        Path to a single ``all_requests_profiler_traces.json``, or a list of
        paths for comparison mode.  When more than one path is provided the
        report gains a ``🔀 Compare`` tab showing A-vs-B deltas; all other
        tabs show Run A data unchanged.
    config_path:
        Path to the eval config YAML (provides pricing).
    output_path:
        Destination HTML file.  Defaults to ``<first_trace_dir>/tokenomics_report.html``.
    """
    if isinstance(trace_path, str):
        trace_paths: list[str] = [trace_path]
    else:
        trace_paths = list(trace_path)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    pricing_raw = (config.get("tokenomics") or {}).get("pricing") or {}
    pricing = PricingRegistry.from_dict(pricing_raw)

    run_datas: list[dict] = []
    for tp in trace_paths:
        profiles = parse_trace(tp, pricing)
        if not profiles:
            print(f"WARNING: no request profiles parsed — check {tp}", file=sys.stderr)

        predicted_osl_map = _load_csv_predictions(tp)
        if predicted_osl_map:
            print(f"Loaded {len(predicted_osl_map)} NOVA-Predicted-OSL values from {Path(tp).name}.")

        rd = _build_report_data(profiles, pricing, config_path, predicted_osl_map)
        # In multi-run mode use the trace's parent directory name as the run label
        # so the comparison tab can distinguish "run_a" from "run_b".
        if len(trace_paths) > 1:
            rd["label"] = Path(tp).parent.name or Path(tp).stem
        run_datas.append(rd)

    primary = run_datas[0]
    if len(run_datas) >= 2:
        cmp = _build_comparison_data(run_datas)
        primary["comparison"] = cmp
        print(
            f"Comparison mode: "
            f"Run A ({cmp['label_a']}) = {cmp['num_queries_a']} queries, "
            f"Run B ({cmp['label_b']}) = {cmp['num_queries_b']} queries, "
            f"{cmp['num_common_queries']} aligned by query ID."
        )
        if cmp["num_common_queries"] == 0:
            print(
                "  WARNING: no overlapping query IDs — per-query deltas will be empty.\n"
                "  Make sure both runs use the same filter.allowlist.",
                file=sys.stderr,
            )
    else:
        primary["comparison"] = None

    html = render_html(primary)

    if output_path is None:
        output_dir = (config.get("eval") or {}).get("general", {}).get("output_dir")
        if output_dir:
            output_path = str(Path(output_dir) / "tokenomics_report.html")
        else:
            output_path = str(Path(trace_paths[0]).parent / "tokenomics_report.html")

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"Report written → {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a tokenomics HTML report from a NAT profiler trace.")
    parser.add_argument(
        "--trace",
        required=True,
        action="append",
        metavar="TRACE",
        help=(
            "Path to all_requests_profiler_traces.json.  "
            "Repeat the flag to compare multiple runs (e.g. --trace run_a/traces.json --trace run_b/traces.json)."
        ),
    )
    parser.add_argument("--config", required=True, help="Path to the eval config YAML")
    parser.add_argument(
        "--output",
        default=None,
        help="Output HTML path (default: <first_trace_dir>/tokenomics_report.html)",
    )
    args = parser.parse_args()
    generate_report(args.trace, args.config, args.output)
