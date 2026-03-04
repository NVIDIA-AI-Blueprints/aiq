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

"""Deep research agent orchestrator using three-tier architecture.

The orchestrator calls planner_agent and researcher_agent as NAT-registered tools.
Each is an independent @register_function that internally manages its own sub-agents.
No SubAgentMiddleware is needed on the orchestrator — just tools.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from .custom_middleware import EmptyContentFixMiddleware
from .custom_middleware import EmptyResponseRetryMiddleware
from .custom_middleware import ReportValidationMiddleware
from .custom_middleware import RewriterMiddleware
from .custom_middleware import TodoSanitizationMiddleware
from .custom_middleware import ToolCallBudgetMiddleware
from .custom_middleware import ToolNameSanitizationMiddleware
from .models import DeepResearchAgentState

logger = logging.getLogger(__name__)

# Path to this agent's directory (for loading prompts)
AGENT_DIR = Path(__file__).parent

# Tool names injected by middleware (TodoListMiddleware)
_MIDDLEWARE_TOOL_NAMES = ["write_todos"]

# Tool call budget for orchestrator
_ORCHESTRATOR_TOOL_BUDGET = 24

REPORT_REWRITER_PROMPT = """\
You are a senior research editor. You receive:
1. The user's original research request
2. The research plan — TOC structure and quality constraints the report should satisfy
3. The research briefs — the raw evidence collected by the research team
4. A draft report written from those briefs

The draft is often a good starting point but may have compressed or dropped evidence that the briefs \
contain. Your job is to produce the best possible final report from the available evidence, using the \
draft as your foundation where it is accurate and well-structured.

Read the briefs carefully, then read the draft. Compare them. The briefs are the source of truth.

Fix what's wrong: where the draft contradicts the briefs, correct it. Where the briefs contain \
something important that the draft missed, add it. Where a claim lacks the evidence behind it, \
strengthen it. Fix obvious mistakes like placeholder text or incomplete content.

Improve the narrative: ensure the executive summary synthesizes findings into a clear central thesis. \
Where the draft presents related findings in separate sections, add brief bridges that connect them. \
If the briefs reveal tensions, trade-offs, or contradictions in the evidence, surface those explicitly. \
If comparing the briefs reveals novel insights — patterns across sources, new connections, \
or implications the draft didn't draw out — add them. \
Ensure the conclusion ties back to the executive summary thesis and directly answers the user's question.

Keep the same language and return the full refined report.

Constraints:
- Preserve every section of the original report. If a section heading (##, ###) exists in the \
draft, it must exist in your output. You may improve content within sections, but do not remove \
sections — especially Forward-Looking Synthesis and Conclusion.
- Try to preserve tables, lists, and structured formats from the draft.
- When the draft describes a finding qualitatively that the briefs describe with specific numbers, \
dates, or named entities, substitute the specific version. Recovering concrete evidence is more \
valuable than restructuring prose.
- When the user asked "how much" or requested a number, try to strengthen qualitative hedges to \
specific figures or ranges from the briefs.
- Ensure every [N] citation in the body has a matching entry in Sources. Do not drop cited sources."""


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
    """Deep research orchestrator using three-tier architecture.

    The orchestrator calls two NAT-registered tools:
    - planner_agent: Two-phase planning (scout + architect)
    - researcher_agent: Multi-specialist research (evidence, mechanism, comparison, critique, horizon)

    Both are @register_function NAT functions wrapped as StructuredTool via builder.get_tools().
    The orchestrator has NO SubAgentMiddleware — it just calls tools.

    Workflow:
    1. Call planner_agent(query="...") → receive plan JSON
    2. Call researcher_agent(query="...") x 3-5 → receive synthesized briefs
    3. Constraint gap review via think
    4. Optional gap-fill researcher_agent calls
    5. Write the final report

    Example:
        >>> agent = DeepResearcherAgent(
        ...     llm_provider=provider,
        ...     tools=[planner_agent_tool, researcher_agent_tool],
        ... )
        >>> state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL")])
        >>> result = await agent.run(state)
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool] | None = None,
        *,
        rewriter_llm: Any | None = None,
        max_loops: int = 2,
        verbose: bool = True,
        callbacks: list[Any] | None = None,
        timeout: int = 600,
    ) -> None:
        """
        Initialize the deep researcher orchestrator.

        Args:
            llm_provider: LLMProvider for role-based LLM access.
            tools: Sequence of LangChain tools — should include planner_agent and
                   researcher_agent as StructuredTools from builder.get_tools().
            rewriter_llm: Optional LLM for post-report refinement. If set, the final
                report is refined against researcher briefs using this model.
            max_loops: Maximum number of research loops (default 2).
            verbose: Enable detailed logging.
            callbacks: Optional list of callbacks.
            timeout: Per-question timeout in seconds. 0 = no timeout.
        """
        self.llm_provider = llm_provider
        self.rewriter_llm = rewriter_llm
        self.tools = list(tools) if tools else []
        self.max_loops = max_loops
        self.verbose = verbose
        self.callbacks = callbacks or []
        self.timeout = timeout

        if self.verbose:
            logger.info("Orchestrator tools configured: %d", len(self.tools))
            for t in self.tools:
                logger.info("  - %s: %s", t.name, t.description[:80] if t.description else "")

        self._prompts = self._load_prompts()
        # All tools: think + NAT tools (planner_agent, researcher_agent, etc.)
        self.all_tools = [think, *self.tools]

        self.middleware = self._get_middleware()

    def _get_middleware(self):
        """Get the middleware for the orchestrator.

        No SubAgentMiddleware — planner_agent and researcher_agent are regular tools
        provided by NAT via builder.get_tools().
        """
        valid_tool_names = [t.name for t in self.all_tools] + _MIDDLEWARE_TOOL_NAMES

        middleware = [
            TodoListMiddleware(),
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(valid_tool_names=valid_tool_names),
            TodoSanitizationMiddleware(),
            ToolCallBudgetMiddleware(max_tool_calls=_ORCHESTRATOR_TOOL_BUDGET),
            ToolCallLimitMiddleware(tool_name="researcher_agent", run_limit=8, exit_behavior="continue"),
            ReportValidationMiddleware(min_length=5000, min_sections=2, max_retries=5),
            # RewriterMiddleware: refine report against researcher briefs (opt-in via config)
            *(
                [
                    RewriterMiddleware(
                        model=self.rewriter_llm,
                        prompt=REPORT_REWRITER_PROMPT,
                        tool_names=["researcher_agent", "planner_agent"],
                    )
                ]
                if self.rewriter_llm
                else []
            ),
            EmptyResponseRetryMiddleware(
                min_content_length=1000,
                max_retries=2,
            ),
            ModelRetryMiddleware(
                max_retries=10,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
        ]

        return middleware

    def _load_prompts(self) -> dict[str, str]:
        """Load the orchestrator prompt."""
        prompts = {}
        try:
            prompts["orchestrator"] = load_prompt(AGENT_DIR / "prompts", "orchestrator")
        except Exception as e:
            logger.warning("Failed to load orchestrator prompt: %s, using inline default", e)
            prompts["orchestrator"] = (
                "You are a research orchestrator. Coordinate the research process and produce a polished report."
            )
        return prompts

    def _build_orchestrator_agent(self, state: DeepResearchAgentState):
        """Build the orchestrator agent graph."""
        orchestrator_instructions = render_prompt_template(
            self._prompts["orchestrator"],
            current_datetime=datetime.now().strftime("%Y-%m-%d"),
            clarifier_result=state.clarifier_result,
        )
        return create_agent(
            model=self.llm_provider.get(LLMRole.ORCHESTRATOR),
            system_prompt=orchestrator_instructions,
            tools=self.all_tools,
            middleware=self.middleware,
            state_schema=DeepResearchAgentState,
        ).with_config({"recursion_limit": 1000})

    async def run(self, state: DeepResearchAgentState) -> DeepResearchAgentState:
        """
        Execute deep research with three-tier workflow.

        Args:
            state: DeepResearchAgentState with conversation messages.

        Returns:
            Updated state with final report in messages.
        """

        agent = self._build_orchestrator_agent(state)

        messages = state.messages
        if messages:
            query_content = messages[-1].content
            query = query_content if isinstance(query_content, str) else str(query_content)
            logger.info("=" * 80)
            logger.info("Deep Research Orchestrator: Starting workflow")
            logger.info("Query: %s...", query[:100])
            logger.info("Tools: %s", [t.name for t in self.all_tools])
            logger.info("=" * 80)

        _timeout = self.timeout if self.timeout > 0 else None
        _config = {"callbacks": self.callbacks} if self.callbacks else None

        try:
            result = await asyncio.wait_for(
                agent.ainvoke(state, config=_config),
                timeout=_timeout,
            )

            final_message = "Research failed to produce a report."
            if result and result.get("messages"):
                final_content = result["messages"][-1].content
                final_message = final_content if isinstance(final_content, str) else str(final_content)

            logger.info("=" * 80)
            logger.info("Deep Research Orchestrator: Workflow complete")
            logger.info("Final report length: %d characters", len(final_message))
            logger.info("=" * 80)
            return DeepResearchAgentState.model_validate(result)

        except TimeoutError:
            logger.warning(
                "Deep Research Orchestrator timed out after %ss for query: %s...",
                self.timeout,
                query[:100] if messages else "unknown",
            )
            # Return state with a timeout message so the eval still gets output
            from langchain_core.messages import AIMessage as _AIMessage

            timeout_msg = _AIMessage(
                content=(
                    f"# Research Report (Partial — Timed Out)\n\n"
                    f"The research workflow exceeded the {self.timeout}s time budget "
                    f"and could not produce a complete report. "
                    f"The partial findings gathered before timeout were not recoverable.\n\n"
                    f"## Query\n\n{query if messages else 'N/A'}\n\n"
                    f"## Recommendation\n\n"
                    f"Please retry with a narrower research scope or increased timeout."
                )
            )
            return DeepResearchAgentState(messages=[*state.messages, timeout_msg])

        except Exception as ex:
            logger.error("Deep Research Orchestrator failed: %s", ex, exc_info=True)
            raise
