# AI-Q RAG evaluation scripts

Benchmark a deployed **AI-Q** server with filesystem RAG datasets (`corpus/` + `train.json`). The driver optionally ingests documents into the knowledge layer, runs **shallow research** on each question, then scores responses with RAGAS [NVIDIA metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/nvidia_metrics/) — the same flow as [NVIDIA RAG Blueprint `evaluate_rag.py`](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/scripts/eval/evaluate_rag.py).

Supports **knowledge-layer only**, **web search only**, or **both**, depending on the AI-Q server config and optional `--data-sources`.

## Prerequisites

1. **AI-Q server** running with an API-enabled shallow-research config, for example:

   ```bash
   # Knowledge + web search
   dotenv -f deploy/.env run .venv/bin/nat serve \
     --config_file configs/config_shallow_frag_web.yml

   # Web search only (no corpus ingestion required)
   dotenv -f deploy/.env run .venv/bin/nat serve \
     --config_file configs/config_web_shallow_web_only.yml
   ```

2. **`INFERENCE_HUB_API_KEY`** (preferred) or **`NVIDIA_API_KEY`** in the environment — required for the RAGAS judge (`langchain_nvidia_ai_endpoints`).

3. **Knowledge-layer evals** also need a reachable knowledge API (`/v1/knowledge/health`) and, when ingesting, `TAVILY_API_KEY` is not required unless web search is enabled on the server.

4. **Web-search evals** need `TAVILY_API_KEY` (or another configured search provider) in `deploy/.env`.

5. Optional environment variables:

   | Variable | Purpose |
   |----------|---------|
   | `AIQ_SERVER_URL` | Default AI-Q base URL when `--server-url` is omitted (default `http://localhost:8000`) |
   | `RAG_EVAL_JUDGE_MODEL` | LLM id for RAGAS scoring (default `nvidia/meta/llama-3.3-70b-instruct`) |
   | `RAG_EVAL_JUDGE_BASE_URL` | Judge API base URL (default `https://inference-api.nvidia.com/v1`) |

## Install

From the repository root:

```bash
uv sync --project scripts/eval
uv run --project scripts/eval python scripts/eval/evaluate_aiq_shallow_research.py --help
```

Or work inside this folder (creates `.venv` next to `pyproject.toml`):

```bash
cd scripts/eval
uv sync
uv run python evaluate_aiq_shallow_research.py --help
```

Use the same `--project scripts/eval` / `cd scripts/eval` pattern for every command below.

## Dataset layout

Each `--dataset-paths` entry is a directory containing:

```text
my_dataset/                 ← dataset root (pass this to --dataset-paths)
  corpus/                   ← required; source documents (nested dirs allowed)
    doc_a.pdf
    notes.txt
  train.json                ← required; eval questions and answers
```

`evaluate_aiq_shallow_research.py` validates each root with `validate_dataset_roots()`:

- The path must be a directory.
- `corpus/` must exist (files are discovered recursively).
- `train.json` must be a UTF-8 JSON array.

For **web-only** benchmarks with `--skip-ingestion`, the corpus is still required by validation but is not uploaded.

## What gets measured

- **Ingestion** — time, file counts, and (for PDFs) pages per second; written to `rag_<label>_evaluation_metrics.json`.
- **Quality (RAGAS)** — `AnswerAccuracy` (`nv_accuracy`), `ContextRelevance` (`nv_context_relevance`), `ResponseGroundedness` (`nv_response_groundedness`). Context metrics require non-empty retrieved contexts from knowledge tools; web-only runs may score accuracy only.
- **Token usage** — prompt, completion, cached, and total tokens plus LLM call counts, aggregated from async job events or ATIF step metrics.
- **E2E inference latency** — client-side wall time per successful query (submit → report). Shown in the tqdm postfix (`e2e_avg_s`) and written to `rag_<label>_evaluation_summary.json`. Not stored per row in `rag_<label>_evaluation_data.json`.

## Main entrypoint

`evaluate_aiq_shallow_research.py` — orchestrates collection check/create, document upload, parallel shallow-research inference, RAGAS scoring, and JSON exports.

### Example: single dataset (knowledge layer)

```bash
export INFERENCE_HUB_API_KEY=your_key_here

uv run --project scripts/eval python scripts/eval/evaluate_aiq_shallow_research.py \
  --dataset-paths /path/to/my_dataset \
  --server-url http://localhost:8000 \
  --output-dir results
```

### Example: skip ingestion (collection already populated)

```bash
uv run --project scripts/eval python scripts/eval/evaluate_aiq_shallow_research.py \
  --dataset-paths /path/to/my_dataset \
  --server-url http://localhost:8000 \
  --skip-ingestion \
  --output-dir results
```

### Example: knowledge only

```bash
uv run --project scripts/eval python scripts/eval/evaluate_aiq_shallow_research.py \
  --dataset-paths /path/to/my_dataset \
  --data-sources knowledge_layer
```

### Example: knowledge + web search

```bash
uv run --project scripts/eval python scripts/eval/evaluate_aiq_shallow_research.py \
  --dataset-paths /path/to/my_dataset \
  --data-sources knowledge_layer,web_search
```

### Example: web search only

Use with `config_web_shallow_web_only.yml` and skip ingestion:

```bash
uv run --project scripts/eval python scripts/eval/evaluate_aiq_shallow_research.py \
  --dataset-paths /path/to/my_dataset \
  --data-sources web_search \
  --skip-ingestion \
  --output-dir results
```

## Useful flags

| Flag | Notes |
|------|-------|
| `--server-url` | AI-Q base URL (default `http://localhost:8000` or `AIQ_SERVER_URL`) |
| `--collection` | Override collection name (default: dataset folder basename) |
| `--skip-ingestion` / `--skip-evaluation` | Ingest-only or inference-only partial runs |
| `--force-ingestion` | Delete and recreate the collection before upload |
| `--agent-type` | Async agent type (default `shallow_researcher`) |
| `--data-sources` | Comma-separated source IDs (default: auto-detect from server agent config) |
| `--inference-mode` | `async` (default, `/v1/jobs/async/submit`) or `atif` (`/v1/workflow/atif`) |
| `--thread` | Parallel shallow-research jobs (default `1`; `e2e_avg_s` in tqdm is true per-query latency only when `1`) |
| `--timeout` | Per-query timeout in seconds (default `1800`) |
| `--ingestion-timeout` | Max wait per ingestion batch (default `3600`; scales with batch size) |
| `--batch-size` | Ingestion upload batch size (default `20`) |
| `--file-type` | Corpus type hint for ingestion metrics (default `pdf`) |
| `--output-dir` | Results directory (default `results`) |

## Outputs

Under `--output-dir` (default `results/`), each dataset gets a subfolder named after the dataset directory:

| File | Content |
|------|---------|
| `rag_<label>_evaluation_data.json` | Per-query model outputs, retrieved contexts, token usage, and job artifacts |
| `rag_<label>_evaluation_summary.json` | Mean RAGAS metrics, token usage, and e2e latency summary |
| `rag_<label>_evaluation_results.json` | Full per-query RAGAS score vectors and aggregated token usage |
| `rag_<label>_evaluation_metrics.json` | Structured ingestion + evaluation + token KPIs |

When multiple datasets are evaluated, a combined summary is also written to `rag_evaluation_summary_all.json`.

## Notes

- Default inference uses `POST /v1/jobs/async/submit` with `agent_type=shallow_researcher`, `collection_name` set to the ingested corpus collection, and data sources resolved from the server unless `--data-sources` is set.
- Retrieved contexts for RAGAS are extracted from `knowledge_search` / `knowledge_retrieval` tool outputs in job artifacts (async mode) or ATIF tool observations (ATIF mode).
- Prefer `--inference-mode async` for large benchmarks; ATIF mode is slower but captures the full agent trajectory.
- After changing the API job runner or agent config, restart the AI-Q server so `collection_name` and data sources are applied correctly.
