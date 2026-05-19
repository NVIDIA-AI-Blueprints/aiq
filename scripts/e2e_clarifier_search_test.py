"""End-to-end test for issue #234 fix.

Runs the ClarifierAgent against a real NVIDIA NIM-hosted LLM with a real Tavily
web search tool, using an obscure query the LLM cannot possibly know from
training data. Verifies that the agent issues a search call before falling back
to asking the user for clarification.

Run with:
    PYTHONPATH=src .venv/bin/python scripts/e2e_clarifier_search_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Load deploy/.env if present.
ENV_FILE = Path(__file__).resolve().parents[1] / "deploy" / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

if not os.environ.get("NVIDIA_API_KEY"):
    sys.exit("NVIDIA_API_KEY not set (paste it into deploy/.env)")
if not os.environ.get("TAVILY_API_KEY"):
    sys.exit("TAVILY_API_KEY not set (paste it into deploy/.env)")

from langchain_community.tools.tavily_search import TavilySearchResults  # noqa: E402
from langchain_core.messages import HumanMessage, ToolMessage  # noqa: E402
from langchain_nvidia_ai_endpoints import ChatNVIDIA  # noqa: E402

from aiq_agent.agents.clarifier.agent import ClarifierAgent  # noqa: E402
from aiq_agent.agents.clarifier.models import ClarifierAgentState  # noqa: E402
from aiq_agent.common import LLMProvider  # noqa: E402

try:
    from aiq_agent.agents.clarifier.agent import FORCE_SEARCH_GUIDANCE  # noqa: E402
except ImportError:
    FORCE_SEARCH_GUIDANCE = None  # running against the pre-fix branch

# Test queries:
#  - "obscure": something no LLM can know without searching.
#  - "knowable": something the LLM thinks it knows; in the failure mode it
#    skips the search and just asks "which aspect?".
TEST_QUERIES = {
    "obscure": "Tell me about Project Zphyr-77Q at QXR Industries — what does it do and who works on it?",
    "knowable": "Research the latest NVIDIA AI announcements from 2026",
}
OBSCURE_QUERY = TEST_QUERIES[os.environ.get("AIQ_TEST_QUERY", "knowable")]

# Model defaults to a small open model so the test is cheap to run.
MODEL_NAME = os.environ.get("AIQ_CLARIFIER_TEST_MODEL", "meta/llama-3.3-70b-instruct")


async def main() -> int:
    llm = ChatNVIDIA(model=MODEL_NAME, temperature=0)
    search = TavilySearchResults(max_results=3, name="web_search_tool")

    provider = LLMProvider()
    provider.set_default(llm)

    # The user_prompt_callback should never be invoked if the search-before-ask
    # behavior is working. If it is invoked, we record it so the test can fail
    # loudly.
    user_prompts: list[str] = []

    async def user_prompt_callback(question: str) -> str:
        user_prompts.append(question)
        # If reached, pretend the user said "skip" so the run still terminates.
        return "skip"

    agent = ClarifierAgent(
        llm_provider=provider,
        tools=[search],
        user_prompt_callback=user_prompt_callback,
        max_turns=2,
    )

    state = ClarifierAgentState(messages=[HumanMessage(content=OBSCURE_QUERY)])
    print(f"Model: {MODEL_NAME}")
    print(f"Query: {OBSCURE_QUERY}\n")

    final_state = await agent.graph.ainvoke(state, config={"callbacks": []})

    # Pull the final messages out for inspection.
    if isinstance(final_state, dict):
        messages = final_state["messages"]
        force_search_used = final_state.get("force_search_used", False)
    else:
        messages = final_state.messages
        force_search_used = getattr(final_state, "force_search_used", False)

    tool_calls_made = sum(
        len(getattr(m, "tool_calls", None) or []) for m in messages
    )
    tool_results = sum(1 for m in messages if isinstance(m, ToolMessage))
    forced = bool(force_search_used)

    print("=" * 72)
    print("Conversation trace")
    print("=" * 72)
    for i, m in enumerate(messages):
        kind = type(m).__name__
        content = str(getattr(m, "content", "")).replace("\n", " ")[:160]
        extra = ""
        if getattr(m, "tool_calls", None):
            extra = f"  tool_calls={[(tc.get('name'), tc.get('args')) for tc in m.tool_calls]}"
        print(f"{i:>2}. {kind}: {content}{extra}")

    print()
    print("=" * 72)
    print("Verdict")
    print("=" * 72)
    print(f"  user_prompt_callback invocations : {len(user_prompts)}")
    print(f"  total tool_calls emitted by LLM  : {tool_calls_made}")
    print(f"  total ToolMessages (results)     : {tool_results}")
    print(f"  force_search guidance injected   : {forced}")

    if tool_calls_made >= 1:
        print("\nPASS: the LLM issued at least one search before any user prompt.")
        return 0
    print("\nFAIL: the LLM never issued a search.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
