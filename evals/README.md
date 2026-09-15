# Final-answer evaluation

For each CSV question, the runner calls the agent, receives its complete answer (including an
asynchronous report when generated), and sends it to an LLM judge. It exports the answers,
judgments, latency and aggregate metrics. There is no deterministic answer scoring.

## Run

From the repository root:

```bash
uv run --no-sync python -m evals.run_eval \
  --endpoint http://localhost:8000/v1/chat/completions \
  --upload-file "Project Solace Operating Model Mock.xlsx" \
  --judge-endpoint https://YOUR_JUDGE_HOST/v1/chat/completions \
  --judge-model YOUR_JUDGE_MODEL \
  --stream --timeout 1800
```

Set `RAG_EVAL_API_KEY` and `RAG_EVAL_JUDGE_API_KEY` in your environment if authentication is
required. No `.env` file is loaded automatically. The judge is always used; the old `--judge`
flag is removed. Judge endpoint and model must be configured before any agent requests run.

Defaults:

- Dataset: `evals/project_solace_retrieval_ground_truth.csv`
- Detailed CSV: `evals/results/answers.csv`
- Summary JSON: `evals/results/summary.json`

`evals/run.sh` is configured to upload `Project Solace Operating Model Mock.xlsx` before every run:

```bash
bash evals/run.sh
```

With `--upload-file`, the runner creates a new collection, uploads the workbook through AI-Q's
multipart document endpoint, and waits for successful ingestion before asking any questions.
It uses that collection for all questions in the run. No collection name needs to be supplied.
The workbook is uploaded once per run. Every question starts with fresh conversation history,
while reusing that uploaded collection. The runner automatically sends `x-aiq-stateless: true`
to the agent; this opt-in backend behavior uses a new checkpoint/citation registry for every
request and skips prior report context (including an explicit `active_report_job_id`).
The backend also binds the uploaded collection from request headers for the duration of the
agent call, then restores the previous context, including on errors. This handles the installed
NAT streaming route clearing its HTTP session context before the response iterator runs.
Normal chat requests without this header keep their existing behavior. Restart the AI-Q backend
after updating `src/aiq_agent/agents/chat_researcher/register.py` so it recognizes the header;
an older server will ignore it and continue sharing history. The judge does not receive it.

Setup time is separate from answer latency and is exported as `ingestion.latency_ms` in the
summary, alongside the file path and generated collection name. `--upload-timeout` defaults to
1800 seconds; ingestion status polling uses `--poll-interval`. Status GETs retry transient errors;
collection creation and upload POSTs are not replayed after errors to avoid duplicate submissions.

If upload or ingestion fails, the run stops before questions or judges are called and preserves
previous output files. Created collections are retained for inspection and follow the backend's
retention policy. The setup step needs working `/v1/collections` and document-ingestion routes;
`503: Knowledge API not configured` means the server has no active ingestor for those routes.

If Excel embedding returns HTTP 400, the backend logs `Excel embedding HTTP 400` with the
model, one-based batch start, batch size, actual rejected input character counts, matching sheet/cell
ranges, and a bounded provider response. Empty input counts/ranges mean the failed request body
was unavailable. Configured credentials
and full chunk text echoed in the response are redacted. The original error still fails ingestion;
no retry or embedding settings change. Restart the backend after applying the logging change.

To reuse an existing collection instead, omit `--upload-file` and supply `--collection`. These
options are mutually exclusive. The runner sets the `conversation-id` header automatically for
fresh uploads. Only the question is sent to the agent, without ground truth. Use `--limit 5` for
a small run.

## Judge

Edit [`judge_prompt.md`](judge_prompt.md) to change the judging instructions, or supply another
file with `--judge-prompt`. The prompt is loaded once per run as a system message. The separate
user message contains the question, expected answer, complete candidate answer, answer type,
annotation notes, numeric tolerance, and date order. No retrieved chunks are sent.

The LLM decides correctness, including equivalent formats, entity/period/metric/label bindings,
rounding allowed by the notes, and partial credit for lists. Python only validates the returned
JSON shape and score range; it does not compare answer values or override the LLM's judgment.

Expected judge output:

```json
{"score": 1, "is_correct": true, "reason": "All expected facts are correctly stated."}
```

`score` ranges from 0 to 1. For lists, the prompt asks for the fraction of expected facts answered
correctly. `is_correct` is true only for a score of 1. Numeric tolerance is supplied to the LLM,
not enforced by a Python comparison. Dates default to DD/MM/YYYY: `2/11/2026` means November 2.

Failed agent requests are not judged. Judge errors or malformed verdicts get score 0,
`scoring_method=judge_error`, and `needs_review=true`; there is no fallback scorer. These rows
remain in the accuracy denominator, and judge failures are counted separately from agent failures.
LLM judgments can be wrong; the exported reason allows review.

## Reports, latency and retries

Regular JSON and SSE chat responses are supported. AI-Q `job_escalation` messages trigger polling
of the same server's job status endpoint, followed by fetching the completed report. The full
report Markdown is stored as `agent_answer`; drafts and handoff messages are not scored.
`answer_source` distinguishes fetched `report` text from inline `chat` answers.

`latency_ms` equals `total_latency_ms`: elapsed time immediately before the initial POST through
receipt of the complete final answer/report, including polling and retry backoff. Queueing,
judging and export are excluded. Judge latency is a separate field.

The timeout covers a whole attempt, including report generation and download. Its default is
300 seconds; use `--timeout 1800` for longer reports. Polling defaults to every 2 seconds.
Transport errors, timeouts, unfinished streams, and HTTP 408/429/5xx are retryable. Once a report
job is known, retries resume that job instead of submitting another. Before the handoff is
received, a retry can duplicate server work if the original response was lost.

First/final attempt durations and each attempt's status, error and stage are recorded separately.
The timeout resets for each retry. Failed/interrupted jobs or missing final reports are request
failures. Exhausting the retry budget does not cancel a running server job.

## Configuration

Every CLI flag also accepts `RAG_EVAL_` plus its uppercase name with hyphens replaced by
underscores, e.g. `RAG_EVAL_JUDGE_MODEL`. CLI values override environment values. Run `--help`
for all options.

| Options | Defaults |
| --- | --- |
| `--endpoint`, `--api-key`, `--model`, `--collection` | Localhost port 8000 chat completions; others empty |
| `--dataset`, `--output-csv`, `--summary-json` | Paths above |
| `--upload-file`, `--upload-timeout` | Optional file path, 1800 seconds for setup |
| `--judge-endpoint`, `--judge-model`, `--judge-api-key` | Endpoint/model required; key optional |
| `--judge-prompt`, `--judge-timeout` | `evals/judge_prompt.md`, 120 seconds |
| `--timeout`, `--poll-interval`, `--concurrency` | 300 seconds, 2 seconds, 1 worker |
| `--stream`, `--limit` | false, 0 (all questions) |
| `--retries`, `--retry-delay`, `--max-retry-delay` | 2 extra attempts, 1 second, 30 seconds |
| `--numeric-tolerance`, `--date-order` | 0.000001, dmy; passed to judge |
| `--headers`, `--extra-body` | JSON objects, both `{}`; agent requests only |

The former `--relative-tolerance` and `--display-rounding` options were removed with deterministic
scoring. Rounding guidance now lives in the prompt and dataset notes.

## Outputs and adaptation

The CSV includes the requested question, reference, answer, score, correctness, method, reason,
latency, HTTP status and error columns, plus grouping fields and retry/judge diagnostics. Rows
are flushed in completion order. The summary includes overall/grouped accuracy, mean component
score, average/median/P90/P95/minimum/maximum latency, latency by difficulty, and failure counts/rates.
Primary latency statistics use successful agent requests; an additional set includes failed ones.
Percentiles use linear interpolation at `(n-1)*p`. Rates and scores are fractions from 0 to 1.

Runs replace their selected outputs. On interruption, completed CSV rows remain but the summary
is not updated. Exit codes: 0 completed without request/judge failures; 1 completed with failures;
2 invalid configuration/input or failed upload setup; 130 interrupted. Low answer accuracy alone does not change the code.

Request/response adaptation points are marked in [`agent_api.py`](agent_api.py).
[`reports.py`](reports.py) contains the AI-Q report job contract; [`upload.py`](upload.py) handles per-run ingestion. Other submission/status formats
need adapter changes. Only final answers are evaluated, never retrieval quality or retrieved chunks.

Uses Python 3.11+ and the project's existing `httpx` dependency. Offline validation:

```bash
uv run --no-sync pytest -q evals/tests
uv run --no-sync ruff check evals
uv run --no-sync ruff format --check evals
```
