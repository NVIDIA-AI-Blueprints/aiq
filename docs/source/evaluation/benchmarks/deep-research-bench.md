<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# AI-Q DRB Evaluator

[DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench/tree/main) is one of the most popular benchmarks for evaluating deep research agents. The benchmark was introduced in [DeepResearch Bench: A Comprehensive Benchmark for Deep Research Agent](https://arxiv.org/pdf/2506.11763). It contains 100 research  tasks (50 English, 50 Chinese) from 22 domains. It proposed 2 different evaluation metrics: RACE and FACT to assess the quality of the research reports.

- RACE: measures report generation quality across 4 dimensions
    - Comprehensiveness
    - Insight
    - Instruction Following
    - Readability
- FACT: evaluates retrieval and citation system using
    - Average Effective Citations: average # of valuable, verifiably supported information an agent retrieves and presents per task.
    - Citation Accuracy: measures the precision of an agent's citations, reflecting its ability to ground statements with appropriate sources correctly.

## Package

This package provides two NeMo Agent Toolkit evaluators for evaluating deep research agents with PhD-level research tasks:

- **RACE** (Reference-based Adaptive Criteria-driven Evaluation): Evaluates report generation quality
- **FACT** (Framework for Factual Abundance and Citation Trustworthiness): Evaluates citation accuracy

## Installation

```bash
uv pip install -e ./frontends/benchmarks/deepresearch_bench
```

## Dataset Setup

The dataset files are not included in the repository. Download them before running evaluation:

1. Download from the [DeepResearch Bench GitHub repository](https://github.com/Ayanami0730/deep_research_bench)
2. Place the files in `frontends/benchmarks/deepresearch_bench/data/`:
   - `drb_full_dataset.json` (required)
   - `criteria.jsonl` (required)

| Filter | Count | Description |
|--------|-------|-------------|
| Default (in config) | 16 | Predefined English sample for testing |
| Full | 100 | All questions (50 English + 50 Chinese) |

## Prerequisites

### Judge model and API key

The RACE evaluator uses an LLM judge to score reports. The default config (`config_deep_research_bench.yml`) is set up to use **OpenAI GPT-5** as the judge.

1. **Choose a judge model** -- Use a capable model for consistent scoring, for example:
   - **OpenAI** -- GPT-4o, GPT-5 (using `OPENAI_API_KEY`)
   - **Gemini** -- Gemini 2.5 Pro or Flash

2. **Obtain an API key** for the provider you chose (OpenAI or Gemini).

3. **Set the key** in `deploy/.env` (recommended) or export it:
   ```bash
   # For OpenAI judge (default in config_deep_research_bench.yml)
   OPENAI_API_KEY=your_openai_key

   # For Gemini judge (if you switch the config to use a Gemini LLM)
   GEMINI_API_KEY=your_gemini_key
   ```

4. **Use a different judge in the config** -- Update `llms:` in the config and set `eval.evaluators.race.llm_name` to that LLM name. Ensure the corresponding API key is set.

### Other API keys (agent and tools)

The agent and tools also need keys (set in `deploy/.env` or the environment):

```bash
export TAVILY_API_KEY=your_key              # Web search (Tavily)
export SERPER_API_KEY=your_key              # Paper search (Serper)
export NVIDIA_API_KEY=your_key               # Agent execution (integrate.api.nvidia.com)
export JINA_API_KEY=your_key                # Optional: FACT evaluator (citation scraping)
```

## Quick Start

Using the default evaluation config (`config_deep_research_bench.yml`):

```bash
source .venv/bin/activate
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench.yml
```

Results are written to `frontends/benchmarks/deepresearch_bench/results` (or the `output_dir` set in the config).

## Evaluators

### RACE Evaluator

Compares generated reports against reference articles using an LLM judge. The default config (`config_deep_research_bench.yml`) uses **OpenAI GPT-5**; internal configs use **Gemini 2.5 Pro** through NVIDIA Inference API.

**Configuration:**

```yaml
evaluators:
  race:
    _type: drb_race_evaluator
    llm_name: gemini_judge
    criteria_file: path/to/criteria.jsonl  # Optional
```

**Dimensions:**

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Comprehensiveness | 30% | Coverage of topic |
| Insight/Depth | 35% | Quality of analysis |
| Instruction Following | 20% | Adherence to task requirements |
| Readability | 15% | Writing quality |

**Score:** 0-100 scale

### FACT Evaluator

Verifies citation accuracy:

1. Extract URLs from generated content
2. Scrape cited webpages through Jina API
3. Validate claims against source content

**Configuration:**

```yaml
evaluators:
  fact:
    _type: drb_fact_evaluator
    llm_name: gemini_flash
    jina_api_key: ${JINA_API_KEY}  # Optional, can use env var
```

**Metrics:**

| Metric | Description |
|--------|-------------|
| Citation Accuracy | Percentage of valid citations |
| Total Citations | Number of URLs cited |
| Valid Citations | Number of verified citations |



## Multi-Run Evaluation Scripts

For more reliable evaluation results, you can run multiple evaluations and aggregate the scores. Two scripts are provided for this purpose:

### `scripts/run_drb_multi_eval_seq.sh`

Runs DRB evaluation 2 times sequentially (configurable with `--runs N`):

- Saves each run to an `aggregated_results` directory
- Automatically runs aggregation after all runs complete
- You will need to update the local repo path, environment variables, and venv/conda configuration for executing `nat eval`

### `scripts/aggregate_drb_scores.py`

Aggregates scores from multiple evaluation runs:

- Loads `race_output.json` from each run folder
- Filters out failed runs (score < 5)
- Calculates per-question mean and standard deviation scores
- Extracts fine-grained metrics (comprehensiveness, insight, instruction_following, readability)
- Outputs final aggregated metrics to the `--output` path

### Usage

Run everything (2 runs + aggregation):

```bash
./frontends/benchmarks/deepresearch_bench/scripts/run_drb_multi_eval_seq.sh
```

Run aggregation only (on existing results):

```bash
python frontends/benchmarks/deepresearch_bench/scripts/aggregate_drb_scores.py \
    --input-dir "frontends/benchmarks/deepresearch_bench/aggregated_results_*" \
    --output "results/drb_aggregated_results.json"
```

## W&B Tracking

Evaluation runs are tracked using [Weights & Biases Weave - deep-researcher-v2 project](https://wandb.ai/nvidia-aiq/deep-researcher-v2/weave) for experiment tracking and observability.

### Configuration

Enable W&B tracking in your config file under `general.telemetry.tracing`:

```yaml
general:
  telemetry:
    tracing:
      weave:
        _type: weave
        project: "deep-researcher-v2"

eval:
  general:
    workflow_alias: "aiq-deepresearch-v2-baseline"
```

### workflow_alias

The `workflow_alias` parameter provides a workflow-specific identifier for tracking evaluation runs:

| Parameter | Description |
|-----------|-------------|
| `workflow_alias` | Unique identifier for the workflow variant being evaluated. Used to group and compare runs across different configurations, models, or dataset subsets. |


## Configuration Files

| Config | Description |
|--------|-------------|
| `configs/config_deep_research_bench.yml` | Default: Nemotron for agent, OpenAI GPT-5 for RACE judge. Use this for the quickstart. |
