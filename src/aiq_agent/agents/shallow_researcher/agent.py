# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shallow research agent for fast, bounded research with tool-calling."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt import tools_condition

from aiq_agent.common import get_source_id_for_tool
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.citation_verification import SourceEntry
from aiq_agent.common.citation_verification import SourceRegistry
from aiq_agent.common.citation_verification import extract_sources_from_tool_result
from aiq_agent.common.citation_verification import get_session_registry
from aiq_agent.common.citation_verification import sanitize_report
from aiq_agent.common.citation_verification import verify_citations

from ...common import LLMProvider
from ...common import LLMRole
from .models import ShallowResearchAgentState

logger = logging.getLogger(__name__)


# Path to this agent's directory (for loading prompts)
AGENT_DIR = Path(__file__).parent


def _append_minimal_citation(report_text: str, source: SourceEntry) -> str:
    """Append one verified citation when the model omitted references."""
    citation_target = source.url or source.citation_key
    if not citation_target:
        return report_text

    # verify_citations may strip every citation line under a **References:**
    # (or ## References / ## Sources) header and leave the empty header
    # behind. Drop that trailing header before we append our own so the final
    # output has exactly one references section.
    content = report_text.rstrip()
    content = re.sub(
        r"\n{1,2}\*\*References:?\*\*\s*$",
        "",
        content,
        flags=re.IGNORECASE,
    ).rstrip()
    content = re.sub(
        r"\n{1,2}#{2,3}\s+(?:References|Sources)\s*$",
        "",
        content,
        flags=re.IGNORECASE,
    ).rstrip()
    if content.endswith((".", "!", "?")):
        content = f"{content[:-1]} [1]{content[-1]}"
    else:
        content = f"{content} [1]"

    if source.url:
        title = source.title or source.url
        reference = f"- [1] {title} - {source.url}"
    else:
        reference = f"- [1] {citation_target}"

    return f"{content}\n\n**References:**\n{reference}"


class ShallowResearcherAgent:
    """
    Shallow research agent for fast, bounded research with tool-calling.

    This agent performs quick lookups and straightforward queries using a
    LangGraph StateGraph with tool-calling capabilities. It generates optional
    mini-plans for multi-step queries and executes bounded tool-calling loops.

    The agent is NAT-independent and receives all dependencies via constructor.

    Example:
        >>> from aiq_agent.common import LLMProvider, LLMRole
        >>> provider = LLMProvider()
        >>> provider.set_default(my_llm)
        >>>
        >>> from lib.models import ShallowResearchAgentState
        >>> agent = ShallowResearcherAgent(
        ...     llm_provider=provider,
        ...     tools=[web_search_tool, doc_search_tool],
        ...     max_tool_iterations=5,
        ... )
        >>> state = ShallowResearchAgentState(messages=[HumanMessage(content="What is CUDA?")])
        >>> result = await agent.run(state)
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool],
        *,
        system_prompt: str | None = None,
        max_llm_turns: int = 10,
        max_tool_iterations: int = 5,
        callbacks: list[Any] | None = None,
    ) -> None:
        """
        Initialize the shallow researcher agent.

        Args:
            llm_provider: LLMProvider for role-based LLM access.
            tools: Sequence of LangChain tools for research.
            system_prompt: Optional custom system prompt. If not provided,
                          loads system.j2 from prompts.
            max_llm_turns: Maximum LLM interaction turns (default 10).
            max_tool_iterations: Maximum tool-calling iterations before forcing
                                synthesis (default 5).
            callbacks: Optional list of LangGraph callbacks.
        """
        self.llm_provider = llm_provider
        self.tools = list(tools)
        self.max_llm_turns = max_llm_turns
        self.max_tool_iterations = max_tool_iterations
        self.callbacks = callbacks or []

        # Load prompts
        self.system_prompt = system_prompt or self._load_system_prompt()

        # Build tools info for prompt rendering
        self.tools_info = self._build_tools_info()

        # Source registry for citation verification (standalone mode fallback)
        self.source_registry = SourceRegistry()

        # Build the LangGraph
        self._graph = self._build_graph()

    def _load_system_prompt(self) -> str:
        """Load the default system prompt."""
        try:
            return load_prompt(AGENT_DIR / "prompts", "researcher")
        except Exception:
            logger.warning("Shallow research prompt not found, using inline default")
            return (
                "You are a research assistant. Answer the user's question using the "
                "available tools. Be concise and cite sources when possible.\n\n"
                "{% if tools %}Available tools: "
                "{{ tools | map(attribute='name') | join(', ') }}{% endif %}"
            )

    def _build_tools_info(self) -> list[dict[str, str]]:
        """Build tools information for prompt rendering."""
        tools_info = []
        for tool in self.tools:
            tool_name = getattr(tool, "name", str(tool))
            tool_desc = getattr(tool, "description", "No description available")
            tools_info.append({"name": tool_name, "description": tool_desc})
        return tools_info

    def _get_llm(self) -> BaseChatModel:
        """Get the LLM for shallow research."""
        return self.llm_provider.get(LLMRole.RESEARCHER)

    def _build_graph(self) -> CompiledStateGraph:
        """Build the LangGraph StateGraph."""

        async def agent_node(state: ShallowResearchAgentState) -> dict[str, Any]:
            """Execute the agent with parallel call tracking and context anchoring."""
            messages = state.messages
            user_info = state.user_info
            iterations = state.tool_iterations

            tools_info = state.tools_info if state.tools_info else self.tools_info

            # Get available documents (user-uploaded files with summaries)
            available_documents = state.available_documents or []

            if available_documents:
                logger.debug("ShallowResearcher received %d available documents", len(available_documents))
                for doc in available_documents:
                    logger.debug("  - [file]: %s", "summary available" if doc.summary else "no summary")
            else:
                logger.debug("ShallowResearcher received no available documents")

            # Render system prompt with current datetime and available documents
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rendered_system_prompt = render_prompt_template(
                self.system_prompt,
                tools=tools_info,
                user_info=user_info,
                current_datetime=current_datetime,
                available_documents=[doc.model_dump() for doc in available_documents],
            )
            # DEBUG: Log the system prompt (can be removed in production)
            if os.environ.get("DEBUG_PROMPTS"):
                logger.debug("Rendered system prompt:\n%s", rendered_system_prompt)

            system_message = SystemMessage(content=rendered_system_prompt)

            processed_history = list(messages)

            if os.environ.get("DEBUG_PROMPTS"):
                logger.debug("Rendered system prompt:\n%s", rendered_system_prompt)

            try:
                if iterations >= self.max_tool_iterations:
                    logger.warning("Max iterations (%d) reached. Forcing synthesis.", iterations)

                    # Anchor instruction at the end to combat "Loss in the Middle"
                    synthesis_anchor = HumanMessage(
                        content=(
                            "You have exhausted your research budget. Synthesize the final answer now "
                            "using the citations [1], [2] and the '## References' format. "
                            "Do not attempt any further tool calls."
                        )
                    )

                    full_messages = [system_message] + processed_history + [synthesis_anchor]
                    response = await self._get_llm().ainvoke(full_messages)
                    return {"messages": [response], "tool_iterations": iterations}

                llm_with_tools = self._get_llm().bind_tools(self.tools, parallel_tool_calls=True)
                full_messages = [system_message] + processed_history
                response = await llm_with_tools.ainvoke(full_messages)

                new_iterations = iterations
                if hasattr(response, "tool_calls") and response.tool_calls:
                    added_calls = len(response.tool_calls)
                    new_iterations += added_calls
                    logger.info("Added %d tool calls to budget. Total: %d", added_calls, new_iterations)

                return {"messages": [response], "tool_iterations": new_iterations}

            except Exception as ex:
                logger.error("Failed in agent_node: %s", ex)
                raise

        builder = StateGraph(ShallowResearchAgentState)

        builder.set_entry_point("agent")

        tool_node = ToolNode(self.tools)

        # Per-agent allowlist mirrors the deep researcher: only tools this
        # agent was loaded with are candidates for source capture. The
        # data_source_registry then decides which of those are configured
        # data sources. Having both gates keeps behavior consistent across
        # agents and safe even if the global registry is ever polluted.
        source_tool_names = {t.name for t in self.tools}

        async def tool_node_with_source_capture(state: ShallowResearchAgentState) -> dict[str, Any]:
            """Execute tools and capture source URLs/citations for verification.

            Source capture is gated by two conditions:

            1. The tool must be in this agent's loaded tool set
               (``source_tool_names``) — mirrors the deep researcher's
               middleware allowlist.
            2. The tool must resolve to a configured data source via
               :func:`get_source_id_for_tool` (i.e. declared under
               ``data_sources`` in the workflow YAML).

            Tools that fail either check (internal scratchpads, ad-hoc
            utilities, unregistered MCP servers) are skipped without
            contributing to the citation registry.
            """
            result = await tool_node.ainvoke(state)
            # Resolve registry at call time (not build time) so each request
            # writes to its own session-scoped registry when available.
            active_registry = get_session_registry() or self.source_registry
            for msg in result.get("messages", []):
                if isinstance(msg, ToolMessage) and msg.content:
                    tool_name = getattr(msg, "name", "") or ""
                    if tool_name not in source_tool_names:
                        continue
                    source_id = get_source_id_for_tool(tool_name)
                    if source_id is None:
                        logger.debug(
                            "[CitationRegistry] Skipping non-data-source tool result from %s",
                            tool_name,
                        )
                        continue
                    sources = extract_sources_from_tool_result(tool_name, str(msg.content), source_id=source_id)
                    for source in sources:
                        active_registry.add(source)
                    if sources:
                        logger.info(
                            "[CitationRegistry] Captured %d source(s) from %s: %s",
                            len(sources),
                            tool_name,
                            [s.url or s.citation_key for s in sources],
                        )
            return result

        builder.add_node("agent", agent_node)
        builder.add_node("tools", tool_node_with_source_capture)

        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", "__end__": "__end__"},
        )
        builder.add_edge("tools", "agent")

        return builder.compile()

    async def run(self, state: ShallowResearchAgentState) -> ShallowResearchAgentState:
        """
        Execute shallow research with tool-calling.

        Args:
            state: ShallowResearchAgentState with conversation messages.

        Returns:
            Updated state with response in messages.
        """
        # Resolve the registry for this request: session-scoped (conversation
        # mode) or instance-scoped with clear (standalone mode).  We use a
        # local variable so we never mutate the shared agent instance.
        session_registry = get_session_registry()
        if session_registry is not None:
            registry = session_registry
        else:
            self.source_registry.clear()
            registry = self.source_registry

        recursion_limit = (self.max_llm_turns * 2) + 10
        config = {"recursion_limit": recursion_limit}
        if self.callbacks:
            config["callbacks"] = self.callbacks
        result = await self._graph.ainvoke(state, config=config)

        # Post-process: verify citations against source registry
        validated_result = dict(result)
        if validated_result.get("messages"):
            last_msg = validated_result["messages"][-1]
            if hasattr(last_msg, "content") and last_msg.content:
                content = str(last_msg.content)

                # Step 1: verify citations against registry
                if registry.all_sources():
                    verification = verify_citations(content, registry)
                    logger.debug(
                        "Shallow researcher: citation verification complete — "
                        "%d valid, %d removed, %d sources in registry",
                        len(verification.valid_citations),
                        len(verification.removed_citations),
                        len(registry.all_sources()),
                    )
                    content = verification.verified_report
                    sources = registry.all_sources()
                    if not verification.valid_citations and len(sources) == 1:
                        content = _append_minimal_citation(content, sources[0])
                else:
                    from aiq_agent.common.tool_validation import validate_tool_availability

                    _, available_count, unavailable = validate_tool_availability(
                        self.tools,
                        research_type="shallow research",
                        enable_logging=False,
                    )
                    raise EmptySourceRegistryError(
                        "shallow research",
                        unavailable_tools=unavailable,
                        available_count=available_count,
                    )

                # Step 2: sanitize report (strip body URLs, shortened URLs, unsafe URLs)
                sanitization = sanitize_report(content)
                content = sanitization.sanitized_report

                # Emit verified/sanitized report so the frontend shows the
                # cleaned version (overwrites the raw draft auto-emitted
                # during ainvoke).
                for cb in self.callbacks:
                    if hasattr(cb, "emit_final_report"):
                        cb.emit_final_report(content)
                        break

                if hasattr(last_msg, "model_copy"):
                    validated_result["messages"][-1] = last_msg.model_copy(update={"content": content})
                else:
                    validated_result["messages"][-1] = type(last_msg)(content=content)

        return ShallowResearchAgentState.model_validate(validated_result)

    @property
    def graph(self) -> CompiledStateGraph:
        """Get the compiled LangGraph for direct access."""
        return self._graph
