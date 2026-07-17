<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Profiling and Cost Analysis

The AI-Q blueprint integrates with the NeMo Agent Toolkit (NAT) profiler to capture detailed execution traces from every evaluation run. These traces record every LLM call, tool invocation, token count, and timestamp across the full multi-agent pipeline. A post-eval tokenomics report then combines that trace data with your configured pricing to produce a complete cost and performance breakdown — down to individual LLM calls and external API charges.

```{note}
Profiling is a post-eval analysis feature. You run the agent normally via `nat eval`; the profiler is activated by adding a `profiler:` block to your eval config. No changes to agent code are required.
```

## What the Profiler Captures

Each profiling run produces two output files in `eval.general.output_dir`:

| File | Contents |
|------|----------|
| `all_requests_profiler_traces.json` | One entry per query. Each entry contains every event (LLM calls, tool calls, workflow start/end) with full token usage, timestamps, and model names. |
| `standardized_data_all.csv` | A flat CSV view of the same events, enriched with NAT-computed metrics such as predicted output sequence length (NOVA-Predicted-OSL), token uniqueness, and bottleneck flags. |

## Enabling the Profiler

Add a `profiler:` block under `eval.general` in your config file. The profiling config for the Deep Research Bench is at:

```
frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench_profiling.yml
```

The relevant `eval` section looks like this:

```yaml
eval:
  general:
    workflow_alias: "aiq-deepresearcher"
    output_dir: frontends/benchmarks/deepresearch_bench/results
    max_concurrency: 4
    profiler:
      # Compute inter-query token uniqueness (measures how much prompt content is reused)
      token_uniqueness_forecast: true
      # Estimate expected wall-clock runtime given the observed concurrency pattern
      workflow_runtime_forecast: true
      # Compute ISL/OSL/TPS and related LLM efficiency metrics
      compute_llm_metrics: true
      # Exclude large I/O text from the CSV to keep it structurally valid
      csv_exclude_io_text: true
      # Identify common prompt prefixes that are good candidates for prompt caching
      prompt_caching_prefixes:
        enable: true
        min_frequency: 0.1
      # Identify the critical path and nested bottlenecks in the agent call graph
      bottleneck_analysis:
        enable_nested_stack: true
      # Detect concurrency spikes that cause queuing
      concurrency_spike_analysis:
        enable: true
        spike_threshold: 7
      # Build a prediction trie to generate Dynamo routing hints
      prediction_trie:
        enable: true
        auto_sensitivity: true
        sensitivity_scale: 5
        # Scoring weights (must sum to 1.0)
        w_critical: 0.5
        w_fanout: 0.3
        w_position: 0.2
        w_parallel: 0.0
    dataset:
      _type: json
      file_path: frontends/benchmarks/deepresearch_bench/data/drb_full_dataset.json
      structure:
        question_key: question
        answer_key: expected_output
        generated_answer_key: generated_answer
      filter:
        allowlist:
          field:
            id: [88, 80, 84, 90, 59, 51, 94, 96, 91, 99, 93, 86, 67, 100, 72, 76]
```

### Profiler option reference

| Option | Description |
|--------|-------------|
| `token_uniqueness_forecast` | Measures the fraction of prompt tokens that are unique across queries. High uniqueness means little opportunity for cross-query caching. |
| `workflow_runtime_forecast` | Estimates how long the full dataset would take to process at the observed concurrency level. Useful for capacity planning. |
| `compute_llm_metrics` | Emits per-call ISL, OSL, TPS, and latency into the CSV. Required for the tokenomics report's token distribution charts. |
| `csv_exclude_io_text` | Strips raw prompt/completion text from the CSV output. Keeps the file manageable when completions are long. Does not affect the JSON trace. |
| `prompt_caching_prefixes.min_frequency` | Only report a common prefix if it appears in at least this fraction of calls (0.1 = 10%). Reduces noise from incidental prefix matches. |
| `bottleneck_analysis.enable_nested_stack` | Produces a nested critical-path stack rather than a simple flat one. More accurate for deeply nested agent graphs. |
| `concurrency_spike_analysis.spike_threshold` | Number of simultaneous in-flight LLM calls that constitutes a spike. Spikes cause queuing and inflate p99 latency. |
| `prediction_trie` | Builds a routing trie for NVIDIA Dynamo. Each leaf carries a latency sensitivity score based on position on the critical path, fan-out, and call-index weighting. |

## Running a Profiling Evaluation

```bash
dotenv -f deploy/.env run nat eval \
  --config_file frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench_profiling.yml
```

The profiler runs automatically alongside `nat eval`. When the run completes, the output directory contains:

```
frontends/benchmarks/deepresearch_bench/results/
├── all_requests_profiler_traces.json   # raw per-event trace data
├── standardized_data_all.csv          # flat CSV with NAT metrics
```

```{tip}
You can run a small subset of queries first using the `filter.allowlist` to validate the setup before committing to a full dataset run. The 16 question IDs in the config represent a diverse sample across domains and difficulty levels.
```

---

## Cost Analysis

Running the profiler tells you *what happened*. The tokenomics report tells you *what it cost* — broken down by
model and external tool API, with a best-effort phase view (Orchestrator / Planner / Researcher).

### Why a dedicated cost report?

LLM token costs alone do not capture the full picture of a research agent run:

- **Search APIs are a significant cost driver.** Measure provider call counts for each evaluation run and apply the prices in effect for that run; research fan-out can make tool usage a material share of total cost.
- **Native phase attribution is incomplete.** NAT traces do not consistently expose a role on each LLM call, so
  the current adapter cannot produce authoritative per-role accounting for every deep-research execution path.
- **Cached tokens may be billed at a discount.** Without explicit tracking, you cannot measure cache hit rates or quantify provider-specific savings from prompt caching.

The tokenomics report separately tracks per-tool API charges and reports cache savings alongside raw token costs.
It also infers phase buckets from task timing windows; treat those buckets as directional because the adapter
collapses non-planner task subagents into the researcher bucket and assigns calls outside task windows to the
orchestrator bucket.

### Configuring Pricing

Keep pricing in a **separate YAML** (for example `configs/config_tokenomics_pricing.yml`) and pass that file to the tokenomics report CLI.

Declare prices under `tokenomics.pricing`:

```yaml
tokenomics:
  pricing:
    models:
      "azure/openai/gpt-5.2":
        input_per_1m_tokens: 2.50
        output_per_1m_tokens: 10.00
      "nvidia/nemotron-3-super-120b-a12b":
        input_per_1m_tokens: 0.12
        output_per_1m_tokens: 0.50
        cached_input_per_1m_tokens: 0.10   # optional: omit to bill cached tokens at full input rate
    tools:
      # Key "web_search" matches "advanced_web_search_tool" via substring lookup
      "web_search":
        cost_per_call: 0.016
      "paper_search":
        cost_per_call: 0.0003
    # Fallback for any model not listed above.
    # Set to null to raise an error on unknown models instead.
    default:
      input_per_1m_tokens: 1.00
      output_per_1m_tokens: 4.00
```

You can optionally set `eval.general.output_dir` in that same file so the report’s default output path matches your eval artifacts directory (refer to `config_tokenomics_pricing.yml` in the bench configs).

**Model name lookup** uses exact match first, then substring match, then the `default`. A key of `"gpt-5.2"` matches a trace model name of `"azure/openai/gpt-5.2"` because the key is a substring of the full name.

**Tool name lookup** follows the same rule. A key of `"web_search"` matches `"advanced_web_search_tool"` because `"web_search"` is a substring of the tool name. Unknown tools default to $0 — no error is raised, so you only need to configure tools that have a real per-call cost.

**`cached_input_per_1m_tokens`** is optional. When omitted, cached tokens are billed at the full input rate (no discount). Set it when your model provider charges a reduced rate for KV-cache hits.

### Generating the Report

After `nat eval` completes, run:

```bash
PYTHONPATH=src python -m aiq_agent.tokenomics.report \
  --trace  frontends/benchmarks/deepresearch_bench/results/all_requests_profiler_traces.json \
  --config frontends/benchmarks/deepresearch_bench/configs/config_tokenomics_pricing.yml
```

If the pricing YAML sets `eval.general.output_dir`, the report is written there as `tokenomics_report.html` when you omit `--output`. Otherwise it defaults to `<trace_directory>/tokenomics_report.html`.

If `standardized_data_all.csv` is present in the same directory as the trace, it is automatically loaded to enrich the report with NOVA-Predicted-OSL data.

The output is a **self-contained HTML file** — no server, no dependencies. Open it directly in any browser.

### Report Tabs

The report is organized into six tabs. Each chart includes a subtitle explaining what to look for.

#### Overview

Top-level stat cards: total cost (LLM + tools), LLM cost, tool API cost, cache savings, prompt/completion token totals,
and LLM call count. Below the cards, a per-query summary table, cost breakdown by model, and best-effort phase
buckets.

Use this tab for a quick health check: if tool API cost is comparable to LLM cost, search frequency is a primary optimization target.

#### Cost

| Chart | What it shows |
|-------|---------------|
| Cost Split by Model | Donut chart of budget allocation across models. |
| Cost by Phase | Best-effort Orchestrator / Planner / Researcher buckets. The Researcher bucket can include source-router and writer task calls, while the Orchestrator bucket can include direct researcher calls; do not read either as role-exclusive accounting. |
| Tool API Cost by Tool | Per-tool total cost and call count. Shown as a call-count bar when all tool costs are $0 (pricing not yet configured). |
| Per-Query Cost Distribution | Histogram of query costs. Hidden when fewer than 10 queries are available. A long right tail means a few hard queries are inflating the average. |
| Cost by Phase per Query | Stacked best-effort phase buckets per query. Use this to find outliers, then inspect the trace before attributing a spike to a role. |

#### Latency

LLM and tool call latency at p50/p90/p99. A large gap between p50 and p99 for LLM calls usually means a few completions with very high output sequence length. Tool p90 above 10 s is a retrieval bottleneck.

#### Tokens

The most detailed tab. All statistics are over individual LLM call observations (not per-request aggregates), so percentile distributions are meaningful even for small query sets.

| Chart | What to look for |
|-------|-----------------|
| ISL p50/p90/p99 by model | Rising p99 vs p50 means some calls hit much larger contexts. |
| OSL p50/p90/p99 by model | High p99 OSL means long reasoning chains or verbose outputs driving latency and cost. |
| Context Accumulation (ISL by call index) | Upward slope = history building up; plateau = caching or fresh-start. Dashed line = estimated system-prompt floor. |
| Throughput (TPS by model) | Low TPS with small OSL = network overhead, not slow generation. |
| Token Budget (cache breakdown) | Green = cached (cheaper); grey = uncached; blue = completion. Maximize green. |
| ISL vs Latency scatter | Diagonal trend = prompt-bound; flat cloud = compute-bound. |
| Token Mix by Phase | Token and cache mix across best-effort phase buckets. Source-router and writer task calls can appear as researcher, while direct researcher calls can appear as orchestrator. |
| NOVA-Predicted vs Actual OSL | Pre-call output length estimates vs actual. Hidden when estimates are post-hoc filled (trivially perfect, not informative). |

#### Efficiency

Latency/cost joint analysis: latency vs cost per query scatter, TPS vs ISL scatter, effective cost per 1K output tokens by model, and a model efficiency bubble chart (x = p90 latency, y = cost/1K output tokens, bubble size = call count). Bottom-left on the bubble chart is the ideal operating point.

#### Pricing

Configured input and output prices as bar charts, plus a full LLM pricing table and a tool pricing table.

#### Per-Query

Full per-query table: cost, ISL, OSL, cached tokens, ISL:OSL ratio, LLM call count, workflow duration, and the question text. Useful for identifying which specific queries drove unusual cost or latency.

### Subagent Phase Attribution

The Deep Research Agent has an orchestrator, an optional source router, a planner, parallel researcher workers, and
a writer. The current adapter in `src/aiq_agent/tokenomics/nat_adapter.py` builds timing windows for `task`
invocations whose `subagent_type` it can parse. It maps `planner-agent` windows to `planner-phase` and every other
parsed task subagent to `researcher-phase`. It associates an `LLM_END` with a window using the call's completion
timestamp; calls outside task windows fall into `orchestrator-phase`.

This does not align completely with the current runtime. The optional `source-router-agent`, `planner-agent`, and
`writer-agent` are delegated through `task()`, so source-router and writer calls are normally folded into
`researcher-phase`. Researcher workers are invoked directly by `run_research_batch` rather than through individual
`task()` calls, so their calls can instead appear in `orchestrator-phase`. The researcher bucket is therefore a
mixed task-subagent bucket, and the orchestrator bucket is partly an **unattributed/default bucket**; neither proves
which role's model performed the work.

Phase charts are consequently best-effort diagnostics, not correct per-role cost accounting for the current runtime.
Overall token and cost totals remain useful independently of that distribution, subject to the completeness of the
trace and pricing configuration. Native role metadata on each LLM step, or adapter support for every current
execution path, is required before the phase split can be treated as authoritative.

### Python API

The tokenomics module can also be used programmatically:

```python
import yaml
from aiq_agent.tokenomics import parse_trace, PricingRegistry

with open("frontends/benchmarks/deepresearch_bench/configs/config_tokenomics_pricing.yml") as f:
    config = yaml.safe_load(f)

pricing = PricingRegistry.from_dict(config["tokenomics"]["pricing"])
profiles = parse_trace(
    "frontends/benchmarks/deepresearch_bench/results/all_requests_profiler_traces.json",
    pricing,
)

for prof in profiles:
    print(
        f"Query {prof.request_index}: "
        f"${prof.grand_total_cost_usd:.4f} total "
        f"(${prof.total_cost_usd:.4f} LLM + ${prof.total_tool_cost_usd:.4f} tools), "
        f"{prof.total_prompt_tokens:,} ISL, {prof.total_completion_tokens:,} OSL, "
        f"{prof.cache_hit_rate:.1%} cache hit"
    )
    for ps in prof.phases:
        print(f"  {ps.phase} / {ps.model}: {ps.llm_calls} calls, ${ps.cost_usd:.4f}")
```

`parse_trace` returns one `RequestProfile` per query. Each profile contains per-phase cost and token totals (`prof.phases`), per-call LLM observations (`prof.llm_call_events`), per-call tool observations (`prof.tool_call_events`), and request-level aggregates.
