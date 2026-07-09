"""Trace-based behavioural tests for AI-Q (NeMo Agent Toolkit), using Monocle
Test Tools.

Each test asserts against the Monocle trace a run emits -- which agent ran,
which tools it called, what it was asked, what it produced, and its duration
cost. Two offline tests replay recorded good traces (fast, no keys); one live
test runs the agent end-to-end.

    pytest tests/monocle/ -k "not live"   # offline, no keys
    RUN_LIVE_NVIDIAAIQ=1 pytest tests/monocle/ -k live -s   # live (needs OPENAI + a search key)

NOTE ON TOKENS: no `under_token_limit` here. NAT calls the OpenAI models in
streaming mode without `stream_options.include_usage`, so the response carries
no usage and the `inference.*` spans record only {finish_reason, finish_type}.
This is upstream (NAT), not a Monocle gap -- Monocle captures token counts
whenever the response includes usage. So the suite budgets on
`under_duration(..., span_type="workflow")` instead. The agent name is
"LangGraph" (NAT runs on a LangGraph runtime); the web tool is `web_search_tool`.
"""
import os
import sys
from pathlib import Path

import pytest
from monocle_test_tools import TraceAssertion

# This repo uses `--import-mode=importlib`, which does not put a test's own
# directory on sys.path; make the sibling conftest importable by name.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import TRACES, run_nvidiaaiq  # noqa: E402

# Recorded good traces (captured from this repo under monocle_apptrace 0.8.8).
# Q: "Hi, what can you do?" -- meta/capabilities, answered directly (no tools).
TRACE_INTRO = str(TRACES / "monocle_trace_nvidia-aiq_4a94876861e3ade549dc74fb785e94d9_2026-07-09_13.17.46.json")
# Q: "What is the current stock price of NVIDIA today?" -- live-fact lookup that
# calls web_search_tool once.
TRACE_STOCK = str(TRACES / "monocle_trace_nvidia-aiq_e2961458302a780a27f91a0d86b290dd_2026-07-09_13.25.14.json")


# --- Offline: replay recorded good traces ---------------------------------

def test_capabilities_intro(monocle_trace_asserter: TraceAssertion):
    """Meta/capabilities question. The orchestrator answers directly (routes it
    as a meta_response) -- no tool is called. Real trace: 5 spans, ~2.0s."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_INTRO)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("what can you do")
    monocle_trace_asserter.contains_output("AI Research Assistant")
    monocle_trace_asserter.does_not_call_tool("web_search_tool", "LangGraph")
    monocle_trace_asserter.under_duration(10, span_type="workflow")

    # Eval layer (deferred -- set OKAHU_API_KEY and uncomment to enable):
    # monocle_trace_asserter.with_evaluation("okahu").check_eval("hallucination", "no_hallucination") \
    #     .check_eval("contextual_precision", "high_precision") \
    #     .check_eval("sentiment", "positive") \
    #     .check_eval("bias", "unbiased")


def test_nvda_stock_lookup(monocle_trace_asserter: TraceAssertion):
    """Live-fact lookup. The agent calls web_search_tool once and reports the
    price it found ($202.78, the captured value). Real trace: 11 spans, ~7.7s."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_STOCK)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("stock price of NVIDIA")
    monocle_trace_asserter.contains_output("202.78")
    monocle_trace_asserter.called_tool("web_search_tool", "LangGraph")
    monocle_trace_asserter.under_duration(15, span_type="workflow")

    # monocle_trace_asserter.with_evaluation("okahu").check_eval("hallucination", "no_hallucination") \
    #     .check_eval("contextual_precision", "high_precision") \
    #     .check_eval("sentiment", "positive") \
    #     .check_eval("bias", "unbiased")


# --- Live: run the agent end-to-end ---------------------------------------
# The web-search fact lookup (web_search_tool over the configured provider).
# Output text varies run to run, so it asserts structure + budget with
# contains_any_output kept phrasing-robust.
#
# Opt-in (RUN_LIVE_NVIDIAAIQ=1), one run per process: NAT binds its async
# singletons (module-level locks) to the first event loop, so a second
# asyncio.run() in the same process raises "bound to a different event loop",
# and NAT leaves non-daemon worker threads that keep the interpreter from
# exiting cleanly. So a default `pytest tests/monocle/` skips this (offline
# stays green and exits clean); run it explicitly, e.g.:
#     RUN_LIVE_NVIDIAAIQ=1 pytest tests/monocle/ -k live -s
_LIVE = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_NVIDIAAIQ") != "1",
    reason="opt-in live run (set RUN_LIVE_NVIDIAAIQ=1; run one live test per process -- see note above)",
)


@_LIVE
def test_nvda_stock_lookup_live(monocle_trace_asserter: TraceAssertion):
    """Web-search path: the NVIDIA stock question, run live (web_search_tool)."""
    monocle_trace_asserter.validator.test_workflow(
        run_nvidiaaiq,
        {"test_input": ("What is the current stock price of NVIDIA today?",)},
    )

    monocle_trace_asserter.called_agent("LangGraph")
    monocle_trace_asserter.contains_any_output("NVIDIA", "NVDA", "stock", "price")
    monocle_trace_asserter.called_tool("web_search_tool", "LangGraph")
    monocle_trace_asserter.under_duration(120, span_type="workflow")

    # monocle_trace_asserter.with_evaluation("okahu").check_eval("hallucination", "no_hallucination") \
    #     .check_eval("contextual_precision", "high_precision") \
    #     .check_eval("sentiment", "positive") \
    #     .check_eval("bias", "unbiased")
