# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Deep research agent using deepagents library for multi-phase workflow."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from deepagents.backends import StateBackend
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.citation_verification import sanitize_report
from aiq_agent.common.citation_verification import verify_citations

from .custom_middleware import EmptyContentFixMiddleware
from .custom_middleware import SourceRegistryMiddleware
from .custom_middleware import ToolNameSanitizationMiddleware
from .custom_middleware import ToolResultPruningMiddleware
from .custom_middleware import ToolRetryMiddleware
from .models import DeepResearchAgentState

logger = logging.getLogger(__name__)

# Minimum character count for a report to be considered substantive.
# Used by both _extract_report_content (to decide if write_file fallback is needed)
# and _is_report_complete (to reject too-short reports).
_MIN_REPORT_LENGTH = 1500

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

        self.source_registry_middleware = SourceRegistryMiddleware(
            source_tool_names={t.name for t in self.tools},
        )

        # Create a tool that gives the orchestrator access to verified sources
        registry_middleware = self.source_registry_middleware

        @tool
        def get_verified_sources() -> str:
            """Returns the list of all verified source URLs captured from search tool calls.

            Call this tool during the Synthesize step (Step 5) BEFORE writing the
            final report. It returns every URL and citation key that was returned
            by search tools during research. Use ONLY these sources in your report
            — any other URL will be automatically removed.

            Returns:
                A numbered list of verified sources with titles and URLs.
            """
            source_list = registry_middleware.get_source_list_text()
            if source_list:
                return source_list
            return "No sources captured yet. Run research queries first."

        self.all_tools = [think, get_verified_sources, *self.tools]

        self.middleware = [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(valid_tool_names=[t.name for t in self.all_tools]),
            ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            self.source_registry_middleware,
            ToolResultPruningMiddleware(keep_last_n=3, max_chars=500),
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

    @staticmethod
    def _extract_report_content(messages: list) -> str:
        """Extract report content from the last message, falling back to write_file tool calls if text is too short."""
        if not messages:
            return ""
        last_msg = messages[-1]
        raw = last_msg.content or ""
        if isinstance(raw, list):
            content = " ".join(p.get("text", "") for p in raw if isinstance(p, dict) and p.get("type") == "text")
        else:
            content = raw if isinstance(raw, str) else str(raw)
        if len(content) >= _MIN_REPORT_LENGTH:
            return content
        # If the last message is an AIMessage with a write_file tool call,
        # the LLM may have written the report via tool instead of text output.
        if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
            for tc in last_msg.tool_calls:
                if tc.get("name") == "write_file":
                    file_content = tc.get("args", {}).get("content", "")
                    if isinstance(file_content, str) and len(file_content) > len(content):
                        content = file_content
        return content

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

        content = self._extract_report_content(messages)

        if len(content) < _MIN_REPORT_LENGTH:
            return False, f"too_short ({len(content)} chars)"

        if content.count("## ") < 2:
            return False, "missing_section_headers"

        source_headers = ("## Sources", "## References", "### Sources", "Reference List")
        has_sources = any(h in content for h in source_headers)
        if not has_sources:
            return False, "missing_sources_section"

        # Quick citation quality check — only reject if ALL citations are invalid
        # (full verification with repair/renumbering happens in run() post-processing)
        registry = self.source_registry_middleware._get_registry()
        if registry.all_sources():
            from aiq_agent.common.citation_verification import _CITATION_LINE_RE
            from aiq_agent.common.citation_verification import _REFERENCE_SECTION_RE
            from aiq_agent.common.citation_verification import _URL_IN_LINE_RE
            from aiq_agent.common.citation_verification import _is_knowledge_citation

            ref_match = _REFERENCE_SECTION_RE.search(content)
            if ref_match:
                ref_section = content[ref_match.start() :]
                has_any_valid = False
                for line_match in _CITATION_LINE_RE.finditer(ref_section):
                    ref_text = line_match.group(2).strip()
                    # Check URL citations
                    url_match = _URL_IN_LINE_RE.search(ref_text)
                    if url_match:
                        url = url_match.group(0).rstrip(".,;)")
                        if registry.resolve_url(url):
                            has_any_valid = True
                            break
                        continue
                    # Check knowledge-layer citation keys (lenient — passes registry for fuzzy match)
                    is_kl, citation_key = _is_knowledge_citation(ref_text, registry)
                    if is_kl and citation_key:
                        has_any_valid = True
                        break
                if not has_any_valid:
                    return False, "no_valid_citations"

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
                elif "no_valid_citations" in reason:
                    feedback_msg += (
                        "None of your cited sources match actual tool results. "
                        "Re-check your findings and cite only URLs returned by your search tools."
                    )
                    # Include the consolidated source list so the orchestrator
                    # has an authoritative reference for the retry
                    source_list = self.source_registry_middleware.get_source_list_text()
                    if source_list:
                        feedback_msg += "\n\n" + source_list

                feedback_msg += (
                    " IMPORTANT: Do NOT restart the research from scratch."
                    " First check if /report.md already exists using read_file."
                    " If it does, use that content as your report — just fix the specific issue above"
                    " and return the corrected report in your final message."
                )

                if isinstance(result, dict):
                    next_state = {**result}
                    messages = result.get("messages", [])
                else:
                    next_state = result.model_dump() if hasattr(result, "model_dump") else dict(result)
                    messages = getattr(result, "messages", next_state.get("messages", []))
                next_state["messages"] = list(messages) + [HumanMessage(content=feedback_msg)]

                try:
                    result = await agent.ainvoke(
                        next_state,
                        config={"callbacks": self.callbacks} if self.callbacks else None,
                    )
                    last_error = None
                except Exception as ex:
                    logger.error("Deep Research feedback retry %d failed: %s", attempt + 1, ex, exc_info=True)
                    last_error = ex
                    if "recursion" in str(ex).lower() or "reuse already awaited" in str(ex):
                        raise ex
                    # Non-fatal: ainvoke raised before producing a result, so
                    # `result` still holds the previous iteration's value.
                    # The next loop iteration will rebuild next_state from it.
                    continue

                # Evaluate the feedback-retry result before the next iteration
                is_complete, reason = self._is_report_complete(result)
                if is_complete:
                    logger.info(f"Report completed after feedback retry. Reason: {reason}")
                    break

                # Update state so next iteration builds on progress, not the original state
                state = result

            if result is None and last_error is not None:
                raise last_error

            final_message = "Research failed to produce a report."
            if result and result.get("messages"):
                final_message = self._extract_report_content(result["messages"])

            # Post-process: verify citations against source registry
            if self.source_registry_middleware._get_registry().all_sources():
                verification = verify_citations(final_message, self.source_registry_middleware._get_registry())
                if verification.removed_citations:
                    removed_details = []
                    for c in verification.removed_citations:
                        url_match = re.search(r"https?://\S+", c.get("line", ""))
                        url_str = url_match.group(0).rstrip(".,;)") if url_match else "(no url)"
                        removed_details.append(f"[{c['number']}] {c['reason']}: {url_str}")
                    logger.info(
                        "Citation verification removed %d invalid citation(s):\n  %s",
                        len(verification.removed_citations),
                        "\n  ".join(removed_details),
                    )
                final_message = verification.verified_report
            else:
                raise EmptySourceRegistryError("deep research")

            # Post-process: sanitize report (strip body URLs, shortened URLs, unsafe URLs)
            sanitization = sanitize_report(final_message)
            final_message = sanitization.sanitized_report

            # Re-emit the verified/sanitized report so the frontend overwrites
            # the raw version that on_llm_end auto-emitted during ainvoke().
            for cb in self.callbacks:
                if hasattr(cb, "emit_final_report"):
                    cb.emit_final_report(final_message)
                    break

            if result and result.get("messages"):
                last_msg = result["messages"][-1]
                if hasattr(last_msg, "model_copy"):
                    result["messages"][-1] = last_msg.model_copy(update={"content": final_message})
                else:
                    result["messages"][-1] = type(last_msg)(content=final_message)

            logger.info("=" * 80)
            logger.info("Deep Research Subagent: Workflow complete")
            logger.info("Final report length: %d characters", len(final_message))
            logger.info("=" * 80)
            return DeepResearchAgentState.model_validate(result)

        except Exception as ex:
            logger.error("Deep Research Subagent failed: %s", ex, exc_info=True)
            raise
