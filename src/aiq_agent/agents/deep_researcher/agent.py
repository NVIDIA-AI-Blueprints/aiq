# SPDX-FileCopyrightText: Copyright (c) 2025, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Deep research agent using deepagents library for multi-phase workflow."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from deepagents.backends import StateBackend
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from .custom_middleware import EmptyContentFixMiddleware
from .custom_middleware import ToolNameSanitizationMiddleware
from .models import DeepResearchAgentState

logger = logging.getLogger(__name__)

# Path to this agent's directory (for loading prompts)
AGENT_DIR = Path(__file__).parent


@tool
def think(thought: str) -> str:
    """Use this tool to reason through complex decisions, verify constraints, or
    plan next steps before acting. The tool records your thought without taking
    any action or retrieving new information.

    When to use:
    - Before making a decision: reason through options and trade-offs
    - After receiving information: analyze findings and identify gaps
    - For constraint verification: check if a constraint is satisfied and note PASS/FAIL
    - When planning: outline your approach before executing

    Args:
        thought: Your reasoning, analysis, or verification to record.
    """
    logger.info("Thinking: %s", thought)
    return "Thought recorded."


class DeepResearcherAgent:
    """
    Deep research agent using deepagents library for multi-phase workflow.

    This agent produces publication-ready research reports through an iterative process:

    1. **Planning Phase**: Generate a structured research plan with queries and report
       organization (planner subagent)
    2. **Research Loops**: Execute queries via web search (researcher subagent), then
       synthesize drafts directly in the orchestrator
    3. **Iteration**: Repeat research and synthesis loops to fill gaps
    4. **Citation Management**: Catalog and number sources in the orchestrator
    5. **Finalization**: Produce a polished report with inline citations and references
       directly in the orchestrator

    The agent is NAT-independent and receives all dependencies via constructor.

    Example:
        >>> from aiq_agent.common import LLMProvider, LLMRole
        >>> provider = LLMProvider()
        >>> provider.set_default(my_llm)
        >>> provider.configure(LLMRole.ORCHESTRATOR, orchestrator_llm)
        >>> provider.configure(LLMRole.RESEARCHER, researcher_llm)
        >>> provider.configure(LLMRole.PLANNER, planner_llm)
        >>>
        >>> from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
        >>> agent = DeepResearcherAgent(
        ...     llm_provider=provider,
        ...     tools=[search_tool_a, search_tool_b],
        ... )
        >>> state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL")])
        >>> result = await agent.run(state)
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool] | None = None,
        *,
        max_loops: int = 2,
        verbose: bool = True,
        callbacks: list[Any] | None = None,
    ) -> None:
        """
        Initialize the deep researcher subagent.

        Args:
            llm_provider: LLMProvider for role-based LLM access.
            tools: Optional sequence of LangChain tools for research.
            max_loops: Maximum number of research loops (default 2).
            verbose: Enable detailed logging.
            callbacks: Optional list of callbacks.
        """
        self.llm_provider = llm_provider
        self.tools = list(tools) if tools else []
        self.max_loops = max_loops
        self.verbose = verbose
        self.callbacks = callbacks or []

        if self.verbose:
            logger.info("Tools configured: %d", len(self.tools))

        self._prompts = self._load_prompts()
        self.tools_info = []
        for t in self.tools:
            self.tools_info.append({"name": t.name, "description": t.description})
        self.all_tools = [think, *self.tools]

        self.middleware = [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(valid_tool_names=[t.name for t in self.all_tools]),
            ModelRetryMiddleware(max_retries=10, backoff_factor=2.0, initial_delay=1.0),
        ]

    def _load_prompts(self) -> dict[str, str]:
        """Load all prompts for subagents."""
        prompts = {}
        prompt_names = ["planner", "researcher", "orchestrator"]

        for name in prompt_names:
            try:
                prompts[name] = load_prompt(AGENT_DIR / "prompts", name)
            except Exception as e:
                logger.warning("Failed to load prompt %s: %s, using inline default", name, e)
                prompts[name] = self._get_inline_default(name)

        return prompts

    def _get_inline_default(self, name: str) -> str:
        """Get inline default prompt for fallback."""
        defaults = {
            "planner": "You are a research planning strategist. Create a structured research plan.",
            "researcher": "You are a research investigator. Gather information from available sources.",
            "orchestrator": (
                "You are a research orchestrator. Coordinate the research process and produce a polished report."
            ),
        }
        return defaults.get(name, f"You are a {name} agent.")

    def _get_subagents(self, state: DeepResearchAgentState) -> list[dict[str, Any]]:
        """Build subagent configs with state-dependent prompts (e.g. available_documents)."""
        available_docs = [doc.model_dump() for doc in (state.available_documents or [])]
        return [
            {
                "name": "planner-agent",
                "description": (
                    "Content-driven research planning - iteratively builds evidence-grounded "
                    "outlines through interleaved search and outline optimization"
                ),
                "system_prompt": render_prompt_template(
                    self._prompts["planner"],
                    tools=self.tools_info,
                    available_documents=available_docs,
                ),
                "tools": self.all_tools,
                "model": self.llm_provider.get(LLMRole.PLANNER),
                "middleware": self.middleware,
            },
            {
                "name": "researcher-agent",
                "description": (
                    "Information gathering - executes search queries and synthesizes "
                    "relevant content from available sources"
                ),
                "system_prompt": render_prompt_template(
                    self._prompts["researcher"],
                    current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    tools=self.tools_info,
                    available_documents=available_docs,
                ),
                "tools": self.all_tools,
                "model": self.llm_provider.get(LLMRole.RESEARCHER),
                "middleware": self.middleware,
            },
        ]

    def _build_orchestrator_agent(self, state: DeepResearchAgentState) -> str:
        """Get the orchestrator instructions for the deep research agent."""

        def backend(runtime):
            return CompositeBackend(
                default=StateBackend(runtime),
                routes={
                    "/shared/": StateBackend(runtime),
                },
            )

        available_docs = [doc.model_dump() for doc in (state.available_documents or [])]
        orchestrator_instructions = render_prompt_template(
            self._prompts["orchestrator"],
            current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            clarifier_result=state.clarifier_result,
            available_documents=available_docs,
            tools=self.tools_info,
        )

        agent = create_deep_agent(
            model=self.llm_provider.get(LLMRole.ORCHESTRATOR),
            tools=self.all_tools,
            backend=backend,
            system_prompt=orchestrator_instructions,
            subagents=self._get_subagents(state),
            store=InMemoryStore(),
            context_schema=DeepResearchAgentState,
            middleware=self.middleware,
        )
        return agent.with_config({"recursion_limit": 1000})

    def _is_report_complete(self, result: dict | Any) -> tuple[bool, str]:
        """
        Check if the agent produced a complete report using tool calls or heuristics.
        """
        if isinstance(result, dict):
            messages = result.get("messages", [])
        else:
            messages = getattr(result, "messages", [])
        if not messages:
            return False, "no_messages"

        last_msg = messages[-1]
        content = last_msg.content or ""

        if len(content) < 1500:
            return False, f"too_short ({len(content)} chars)"

        if content.count("## ") < 2:
            return False, "missing_section_headers"

        source_headers = ("## Sources", "## References", "### Sources", "Reference List")
        has_sources = any(h in content for h in source_headers)
        if not has_sources:
            return False, "missing_sources_section"

        giving_up_patterns = [
            "please confirm",
            "do you want me to",
            "should i proceed",
            "choose one",
            "option (1)",
            "option (2)",
            "allow me to",
            "i need your permission",
            "i can't produce",
            "i cannot produce",
            "what i need from you",
        ]
        content_lower = content.lower()
        for pattern in giving_up_patterns:
            if pattern in content_lower:
                return False, f"agent_gave_up (detected: '{pattern}')"

        return True, "complete_via_heuristic"

    async def run(self, state: DeepResearchAgentState) -> DeepResearchAgentState:
        """
        Execute deep research with multi-phase workflow.
        """

        agent = self._build_orchestrator_agent(state)

        messages = state.messages
        if messages:
            query_content = messages[-1].content
            query = query_content if isinstance(query_content, str) else str(query_content)
            logger.info("=" * 80)
            logger.info("Deep Research Subagent: Starting workflow")
            logger.info("Query: %s...", query[:100])
            logger.info("=" * 80)

        result = None
        last_error = None
        try:
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    result = await agent.ainvoke(
                        state,
                        config={"callbacks": self.callbacks} if self.callbacks else None,
                    )
                    last_error = None
                except Exception as ex:
                    logger.error("Deep Research attempt %d failed: %s", attempt + 1, ex, exc_info=True)
                    last_error = ex
                    # If we hit the recursion limit or asyncio error, we might want to stop
                    if "recursion" in str(ex).lower() or "reuse already awaited" in str(ex):
                        raise ex
                    continue

                is_complete, reason = self._is_report_complete(result)
                if is_complete:
                    logger.info(f"Report completed successfully. Reason: {reason}")
                    break

                logger.warning("Report incomplete (attempt %d/%d): %s", attempt + 1, max_retries, reason)

                feedback_msg = f"Your report is not yet complete. Reason: {reason}. "
                if "missing_sources_section" in reason:
                    feedback_msg += "You must include a '## Sources' section listing all URLs."
                elif "too_short" in reason:
                    feedback_msg += "The report is too short. Expand your analysis and add more detail."
                elif "missing_section_headers" in reason:
                    feedback_msg += "Use markdown headers (##) to structure the report."

                feedback_msg += " Please fix this immediately and call 'submit_final_report' when done."

                if isinstance(result, dict):
                    next_state = {**result}
                    messages = result.get("messages", [])
                else:
                    next_state = result.model_dump() if hasattr(result, "model_dump") else dict(result)
                    messages = getattr(result, "messages", next_state.get("messages", []))
                next_state["messages"] = list(messages) + [HumanMessage(content=feedback_msg)]
                result = await agent.ainvoke(
                    next_state,
                    config={"callbacks": self.callbacks} if self.callbacks else None,
                )

            if result is None and last_error is not None:
                raise last_error

            final_message = "Research failed to produce a report."
            if result and result.get("messages"):
                final_content = result["messages"][-1].content
                final_message = final_content if isinstance(final_content, str) else str(final_content)

            logger.info("=" * 80)
            logger.info("Deep Research Subagent: Workflow complete")
            logger.info("Final report length: %d characters", len(final_message))
            logger.info("=" * 80)
            return DeepResearchAgentState.model_validate(result)

        except Exception as ex:
            logger.error("Deep Research Subagent failed: %s", ex, exc_info=True)
            raise
