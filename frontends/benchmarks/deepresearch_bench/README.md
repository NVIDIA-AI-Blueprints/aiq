# AIQ DRB Evaluator

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


### API Keys

```bash
export OPENAI_API_KEY=your_key              # For eval 
export TAVILY_API_KEY=your_key              # For web search
export YOU_API_KEY=your_key                 # For web search (optional)
export NVIDIA_API_KEY=your_key              # For agent execution (integrate.api.nvidia.com)
export OPENAI_API_KEY=your_key              # For frontier model in config (optional)
export GEMINI_API_KEY=your_key              # For Gemini eval 
export JINA_API_KEY=your_key                # For FACT evaluation (optional)
```

## Configuration Files

The following table lists the available configuration files:

| Configuration file | Description |
| --- | --- |
| `frontends/benchmarks/deepresearch_bench/configs/config_ensemble.yml` | Runs the DeepResearch Bench evaluation with a combination of GPT-5.2 model and nemotron. |

## Running Evaluation

### Step 1: Install the dataset

The dataset files are not included in the repository. We have included a script to retrieve them from the [Deep Research Bench Github Repository](https://github.com/Ayanami0730/deep_research_bench/tree/main) and format them for the NeMo Agent Toolkit evaluator.

To download the dataset files, run the following script:

```bash
python frontends/benchmarks/deepresearch_bench/scripts/download_drb_dataset.py
```

### Step 2: Generate reports using NAT evaluation harness

```bash
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/deepresearch_bench/configs/config_ensemble.yml
```

### Step 3: Convert the output into a compatible format
```bash
python frontends/benchmarks/deepresearch_bench/scripts/export_drb_jsonl.py --input <path to your workflow_output.json> --output <path to the output file you want to create with .jsonl extension>
```

### Step 4: Run evaluation
Follow instructions in the [Deep Research Bench Github Repository](https://github.com/Ayanami0730/deep_research_bench/tree/main) to run evaluation and obtain scores.

## Optional: Phoenix Tracing

If your config enables Phoenix tracing, start the Phoenix server before running `nat eval`.

Start server (separate terminal):

```bash
source .venv/bin/activate
phoenix serve
```

## Evaluators

### RACE Evaluator

Compares generated reports against reference articles using **Gemini 2.5 Pro** as an LLM judge.

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

Verifies citation accuracy using **Gemini 2.5 Flash**:

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

Runs DRB evaluation 3 times sequentially:

- Saves each run to `eval/drb_results_run1/`, `eval/drb_results_run2/`, `eval/drb_results_run3/`
- Automatically runs aggregation after all runs complete
- You will need to update the local repo path, environment variables, and venv/conda configuration for executing `nat eval`

### `scripts/aggregate_drb_scores.py`

Aggregates scores from multiple evaluation runs:

- Loads `race_output.json` from each run folder
- Filters out failed runs (score < 5)
- Calculates per-question mean and standard deviation scores
- Extracts fine-grained metrics (comprehensiveness, insight, instruction_following, readability)
- Outputs final aggregated metrics to `eval/drb_aggregated_results.json`

### Usage

Run everything (3 runs + aggregation):

```bash
./scripts/run_drb_multi_eval.sh
```

Run aggregation only (on existing results):

```bash
python scripts/aggregate_drb_scores.py \
    --input-pattern "eval/drb_results_run*/race_output.json" \
    --output "eval/drb_aggregated_results.json"
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
