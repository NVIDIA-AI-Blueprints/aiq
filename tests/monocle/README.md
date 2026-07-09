# AI-Q behavioural tests (Monocle Test Tools)

Trace-based tests that lock in the AI-Q research agent's behaviour. AI-Q runs on
the NeMo Agent Toolkit (NAT); Monocle records each run as a structured trace --
the agent invocation, every tool call, and timings -- and each test asserts
against that trace: which agent ran, which tools it called, what it was asked,
what it produced, and its duration cost. A later prompt, model, or tool change
that regresses the behaviour fails here.

## Layout

- `test_nvidiaaiq.py` — the suite: two offline tests + one live test
- `conftest.py` — Monocle setup, `.env` loading, and `run_nvidiaaiq()`
- `traces/` — recorded good-trace fixtures the offline tests replay
- `requirements.txt` — dependencies

## Tests

| Test | Scenario | What it shows |
|---|---|---|
| `test_capabilities_intro` | "Hi, what can you do?" | direct answer, a `does_not_call_tool` negative, budget |
| `test_nvda_stock_lookup` | Current NVIDIA stock price | `web_search_tool` call, input/output, budget |
| `test_nvda_stock_lookup_live` | The stock question, run live | live run, web-search path, structure + budget |

The offline tests replay recorded traces with duration budgets measured from
those runs (rounded up with headroom). The live test drives the agent
end-to-end and asserts structure and budget only, since the output legitimately
varies run to run.

Note on budgets: NAT traces do not carry token metadata -- the `inference.*`
spans record only finish reasons, no token counts -- so `under_token_limit(...)`
would sum 0 and always pass. This suite omits it and budgets on
`under_duration(..., span_type="workflow")` instead. The agent name asserted
(`LangGraph`) is the real `entity.1.name` on the `agentic.invocation` spans (NAT
runs its research agents on a LangGraph runtime); the web tool is
`web_search_tool`.

## Run

```bash
pip install -r requirements.txt
pytest tests/monocle/ -k "not live"   # offline, no network, no keys
```

The live test is opt-in (`RUN_LIVE_NVIDIAAIQ=1`) and skipped by default.
NAT binds its async singletons to the first event loop, so only one in-process
live run works per process, and NAT leaves non-daemon threads that keep the
interpreter from exiting cleanly. So run the live test in its own process, with
keys in `deploy/.env` (`OPENAI_API_KEY` plus a search key, `EXA_API_KEY`/`SERPER_API_KEY`):

```bash
RUN_LIVE_NVIDIAAIQ=1 pytest tests/monocle/ -k nvda_stock_lookup_live -s
```

They drive the workflow via `configs/config_openai_cli.yml` with an
auto-approving `user_input_callback`, so a human-in-the-loop clarification or
plan-approval interrupt is answered automatically instead of blocking the run.

## Add your own test

1. Run AI-Q under Monocle and capture a trace of a run you're happy with
   (Monocle writes trace JSON to `.monocle/` by default).
2. Move it into `traces/` and load it with
   `monocle_trace_asserter.with_trace_source("file", trace_path=path)`.
3. Assert with the fluent API — `called_agent(...)`, `called_tool(...)`,
   `contains_input/output(...)`, `under_duration(..., span_type="workflow")` —
   then add it alongside the others.

## Evaluations (optional)

Each test carries a commented-out `check_eval("hallucination", ...)` chain.
Monocle can run evaluation checks against a trace; set `OKAHU_API_KEY` and
uncomment to enable.
