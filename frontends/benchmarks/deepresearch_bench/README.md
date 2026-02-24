# AI-Q DRB Evaluator

[DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench/tree/main) is one of the most popular benchmarks for evaluating deep research agents. The benchmark was introduced in [DeepResearch Bench: A Comprehensive Benchmark for Deep Research Agent](https://arxiv.org/pdf/2506.11763). It contains 100 research  tasks (50 English, 50 Chinese) from 22 domains. It proposed 2 different evaluation metrics: RACE and FACT to assess the quality of the research reports.

- RACE: measures report generation quality across 4 dimensions
    - Comprehensiveness
    - Insight
    - Instruction Following
    - Readability
- FACT: evaluates retrieval and citation system using
    - Average Effective Citations: average # of valuable, verifiably supported information an agent retrieves and presents per task.
    - Citation Accuracy: measures the precision of an agent’s citations, reflecting its ability to ground statements with appropriate sources correctly.

## Package

This package provides two NeMo Agent toolkit evaluators for evaluating deep research agents with PhD-level research tasks:

- **RACE** (Reference-based Adaptive Criteria-driven Evaluation): Evaluates report generation quality
- **FACT** (Framework for Factual Abundance and Citation Trustworthiness): Evaluates citation accuracy

## Installation

```bash
uv pip install -e ./frontends/benchmarks/deepresearch_bench
```

## Dataset

| Filter | Count | Description |
|--------|-------|-------------|
| Default (in config) | 16 | Predefined English sample for testing |
| Full | 100 | All questions (50 English + 50 Chinese) |

## Dataset Setup

The dataset files are not included in the repository. Download them before running evaluation:

1. Download from the [DeepResearch Bench GitHub repository](https://github.com/Ayanami0730/deep_research_bench)
2. Place the files in `frontends/benchmarks/deepresearch_bench/data/`:
   - `drb_full_dataset.json` (required)
   - `criteria.jsonl` (required)

## Prerequisites

### Judge model and API key

The RACE evaluator uses an LLM judge to score reports. The default config (`config_deep_research_bench.yml`) is set up to use **OpenAI GPT-5** as the judge.

1. **Choose a judge model** – Use a capable model for consistent scoring, e.g.:
   - **OpenAI** – GPT-4o, GPT-5 (via `OPENAI_API_KEY`)
   - **Gemini** – Gemini 2.5 Pro or Flash

2. **Obtain an API key** for the provider you chose (OpenAI or Gemini).

3. **Set the key** in `deploy/.env` (recommended) or export it:
   ```bash
   # For OpenAI judge (default in config_deep_research_bench.yml)
   OPENAI_API_KEY=your_openai_key

   # For Gemini judge (if you switch the config to use a Gemini LLM)
   GEMINI_API_KEY=your_gemini_key
   ```

4. **Use a different judge in the config** – Update `llms:` in the config and set `eval.evaluators.race.llm_name` to that LLM name. Ensure the corresponding API key is set.

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

Compares generated reports against reference articles using **Gemini 2.5 Pro** (through NVIDIA Inference Hub) as an LLM judge.

**Configuration:**

```yaml
evaluators:
  - _type: drb_race_evaluator
    llm_name: gemini_judge
    criteria_file: path/to/criteria.json  # Optional
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
  - _type: drb_fact_evaluator
    llm_name: gemini_flash
    jina_api_key: ${JINA_API_KEY}  # Optional, can use env var
```

**Metrics:**

| Metric | Description |
|--------|-------------|
| Citation Accuracy | Percentage of valid citations |
| Total Citations | Number of URLs cited |
| Valid Citations | Number of verified citations |



## Multi-run evaluation scripts

For more reliable evaluation results, you can run multiple evaluations and aggregate the scores. Two scripts are provided for this purpose:

### `scripts/run_drb_multi_eval_seq.sh`

Runs DRB evaluation multiple times sequentially (default: 2):

- Saves each run under a directory (e.g. `aggregated_results_<timestamp>` or a name you pass)
- Automatically runs aggregation after all runs complete
- You will need to update the local repo path, environment variables, and venv/conda configuration for executing `nat eval`

### `scripts/aggregate_drb_scores.py`

Aggregates scores from multiple evaluation runs:

- Finds `race_output.json` under each input directory: in `run*/` subdirectories or at the top level
- Filters out failed runs (score below threshold, default 5.0)
- Calculates per-question mean and standard deviation scores
- Extracts fine-grained metrics (comprehensiveness, insight, instruction_following, readability)
- Writes aggregated metrics to the path given by `--output`

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--input-dir` | Yes | One or more directories (or globs like `./results/hybrid_full*`). Each directory may contain `run*/race_output.json` or a top-level `race_output.json`. |
| `--output` | Yes | Output file path for aggregated results (JSON). |
| `--score-threshold` | No | Minimum score to count a run as successful (default: 5.0). |
| `--verbose` | No | Print detailed output. |

### Usage

Run multiple evaluations and aggregate (from project root):

```bash
cd frontends/benchmarks/deepresearch_bench
./scripts/run_drb_multi_eval_seq.sh
```

With a named output directory and three runs:

```bash
./scripts/run_drb_multi_eval_seq.sh --runs 3 "my-experiment"
```

Run aggregation only on existing results. Use a single directory that contains `run1/`, `run2/`, etc. (each with `race_output.json`):

```bash
python scripts/aggregate_drb_scores.py \
    --input-dir results/aggregated_results_20250101_120000 \
    --output results/aggregated_results.json
```

Or pass multiple directories, or a glob that expands to directories:

```bash
python scripts/aggregate_drb_scores.py \
    --input-dir "results/hybrid_full*" \
    --output results/drb_aggregated_results.json
```

Optional: change the failure threshold or enable verbose output:

```bash
python scripts/aggregate_drb_scores.py \
    --input-dir results/my_runs \
    --output results/aggregated_results.json \
    --score-threshold 4.0 \
    --verbose
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


## Other configuration files

The following configs target specific model or workflow variants. For standard use, use `config_deep_research_bench.yml` as in [Quick Start](#quick-start).

| Config | Description |
|--------|-------------|
| `configs/config_deep_research_bench.yml` | Default: Nemotron for agent, OpenAI GPT-5 for RACE judge. Use this for the main quickstart. |