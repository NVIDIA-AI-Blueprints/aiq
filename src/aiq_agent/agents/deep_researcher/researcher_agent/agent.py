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

"""Researcher agent implementation with 6 analytical specialist sub-agents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from ..custom_middleware import EmptyContentFixMiddleware
from ..custom_middleware import EmptyResponseRetryMiddleware
from ..custom_middleware import RewriterMiddleware
from ..custom_middleware import TodoSanitizationMiddleware
from ..custom_middleware import ToolCallBudgetMiddleware
from ..custom_middleware import ToolNameSanitizationMiddleware
from ..models import DeepResearchAgentState

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).parent

_MIDDLEWARE_TOOL_NAMES = ["write_todos"]

# Budget constants
_COORDINATOR_TOOL_BUDGET = 12  # coordinator tool calls: think + task dispatches + synthesis
_SPECIALIST_TOOL_BUDGET = 12  # searches + paper_search + think per specialist

# Rewriter prompt for brief refinement (used by RewriterMiddleware when rewriter_llm is configured)
#
# Informed by trace analysis across v3-v12 (10 tasks, 61 researcher calls):
# - Coordinator synthesis retains only ~40% of specialist evidence on average
# - Specific numbers, named entities, and comparison tables are the most likely to be dropped
# - 3/10 tasks had internal processing artifacts (<tool_call>, <function=think> blocks) leak into briefs
# - The brief is the only path research takes to the final report — lost evidence cannot be recovered later
BRIEF_REWRITER_PROMPT = """\
You are a research brief editor. You receive three things:
1. The user's original research request (for context on what matters)
2. The raw specialist research outputs — the primary evidence
3. A synthesis brief written from those outputs

The synthesis often drops important evidence during compression. Your job is to produce a better brief \
from the same specialist material.

Read all the specialist outputs carefully, then read the synthesis. Improve it by:

- **Recovering dropped evidence.** The specialists often found specific numbers, data tables, named \
entities, source URLs, and analytical findings that the synthesis omits. If it's relevant to the \
user's question, it should be in the brief.
- **Fact-checking.** If the synthesis states a number or claim that contradicts what a specialist \
actually found, use the specialist's version.
- **Cleaning artifacts.** If the synthesis contains raw internal text (XML tags, tool call markup, \
planning monologue, or other processing artifacts), remove them cleanly.
- **Filling gaps.** If any section is incomplete or contains placeholder text, fill it using the \
specialist evidence.
- **Preserving citations.** Keep inline [N] references and the Sources section intact. Do not \
renumber or drop them.

Constraints:
- Work only with information from the specialist outputs. Do not add external knowledge.
- Keep the brief organized by topic, not by which specialist produced it.
- Keep the same language as the original brief.

Return the full improved brief."""


@tool
def think(thought: str) -> str:
    """Use this tool to reason through complex decisions, verify constraints, or
    plan next steps before acting. The tool records your thought without taking
    any action or retrieving new information.

    Args:
        thought: Your reasoning, analysis, or verification to record.
    """
    logger.info("Researcher thinking: %s", thought[:200])
    return "Thought recorded."


class ResearcherAgentImpl:
    """Multi-specialist researcher: dispatches to analytical specialists, then synthesizes.

    Specialists organized by analytical function (not source type):
    - evidence-gatherer: facts, statistics, specific numbers
    - mechanism-explorer: causal explanations, "why/how", frameworks
    - comparator: head-to-head data, benchmarks, rankings
    - critic: counterarguments, limitations, failure cases
    - horizon-scanner: recent developments, trends, predictions

    The coordinator cross-references all specialist outputs to produce a unified brief.
    """

    def __init__(
        self,
        llm: Any,
        tools: Sequence[BaseTool] | None = None,
        *,
        rewriter_llm: Any | None = None,
        verbose: bool = True,
        callbacks: list[Any] | None = None,
        timeout: int = 1200,
    ) -> None:
        self.llm = llm
        self.rewriter_llm = rewriter_llm
        self.tools = list(tools) if tools else []
        self.callbacks = callbacks or []
        self.timeout = timeout

        self._prompts = self._load_prompts()
        self.tools_info = [{"name": t.name, "description": t.description} for t in self.tools]
        self.all_tools = [think, *self.tools]

        self._agent = self._build_agent()

    def _load_prompts(self) -> dict[str, str]:
        """Load all prompts for researcher sub-agents."""
        prompts = {}
        prompt_names = [
            "researcher_coordinator",
            "evidence_gatherer",
            "mechanism_explorer",
            "comparator",
            "critic",
            "horizon_scanner",
            "generalist",
        ]
        for name in prompt_names:
            try:
                prompts[name] = load_prompt(AGENT_DIR / "prompts", name)
            except Exception as e:
                logger.warning("Failed to load prompt %s: %s", name, e)
                prompts[name] = f"You are a {name} agent. Complete the research task described."
        return prompts

    def _build_agent(self):
        """Build the researcher coordinator with 6 specialist sub-agents."""
        current_datetime = datetime.now().strftime("%Y-%m-%d")

        # Define the 5 specialist sub-agents
        specialist_configs = [
            (
                "evidence-gatherer",
                "evidence_gatherer",
                "Finds concrete facts, statistics, specific numbers from authoritative sources "
                "(papers, government data, industry reports). Answers: 'What is true? How much? How many?'",
            ),
            (
                "mechanism-explorer",
                "mechanism_explorer",
                "Finds causal explanations — why things happen, what mechanisms drive outcomes, "
                "theoretical frameworks. Answers: 'Why does this happen? What causes it?'",
            ),
            (
                "comparator",
                "comparator",
                "Finds head-to-head data — benchmarks, rankings, X vs Y comparisons, "
                "trade-off analyses. Answers: 'How do options compare? Which is better and when?'",
            ),
            (
                "critic",
                "critic",
                "Finds counterarguments, limitations, failure cases, edge cases, "
                "alternative perspectives. Answers: 'What could go wrong? What's missing?'",
            ),
            (
                "horizon-scanner",
                "horizon_scanner",
                "Finds recent developments, emerging trends, expert predictions, "
                "trajectory signals from the last 12 months. Answers: 'What's changing? Where is this heading?'",
            ),
            (
                "generalist",
                "generalist",
                "Conducts broad, balanced research without a specific analytical lens. "
                "Adapts approach to what the topic needs — facts, context, mechanisms, comparisons, "
                "or implications. Use when the research question spans multiple modes or doesn't "
                "clearly map to a specialist.",
            ),
        ]

        subagents = []
        for agent_name, prompt_key, description in specialist_configs:
            subagents.append(
                {
                    "name": agent_name,
                    "description": description,
                    "system_prompt": render_prompt_template(
                        self._prompts[prompt_key],
                        current_datetime=current_datetime,
                        tools=self.tools_info,
                    ),
                    "tools": self.all_tools,
                    "model": self.llm,
                    "middleware": [
                        ToolCallLimitMiddleware(
                            tool_name="advanced_web_search_tool", run_limit=8, exit_behavior="continue"
                        ),
                        ToolCallLimitMiddleware(tool_name="paper_search_tool", run_limit=4, exit_behavior="continue"),
                        ToolCallBudgetMiddleware(max_tool_calls=_SPECIALIST_TOOL_BUDGET),
                    ],
                }
            )

        # Sub-agent default middleware
        subagent_middleware = [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(valid_tool_names=[t.name for t in self.all_tools] + _MIDDLEWARE_TOOL_NAMES),
            TodoSanitizationMiddleware(),
            EmptyResponseRetryMiddleware(min_content_length=512, max_retries=2),
            ModelRetryMiddleware(max_retries=10, backoff_factor=2.0, initial_delay=1.0),
        ]

        # Coordinator middleware
        valid_subagent_types = {name for name, _, _ in specialist_configs}
        coordinator_middleware = [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(
                valid_tool_names=[t.name for t in [think]] + _MIDDLEWARE_TOOL_NAMES + ["task"],
                task_subagent_default="generalist",
                valid_subagent_types=valid_subagent_types,
            ),
            ToolCallLimitMiddleware(tool_name="task", run_limit=4, exit_behavior="continue"),
            ToolCallBudgetMiddleware(max_tool_calls=_COORDINATOR_TOOL_BUDGET),
            EmptyResponseRetryMiddleware(min_content_length=512, max_retries=2),
            ModelRetryMiddleware(max_retries=10, backoff_factor=2.0, initial_delay=1.0),
            SubAgentMiddleware(
                default_model=self.llm,
                default_tools=self.all_tools,
                subagents=subagents,
                default_middleware=subagent_middleware,
                general_purpose_agent=False,
            ),
            # RewriterMiddleware: refine coordinator's synthesis against specialist evidence
            *(
                [
                    RewriterMiddleware(
                        model=self.rewriter_llm,
                        prompt=BRIEF_REWRITER_PROMPT,
                        tool_names=["task"],
                    )
                ]
                if self.rewriter_llm
                else []
            ),
        ]

        coordinator_prompt = render_prompt_template(
            self._prompts["researcher_coordinator"],
            current_datetime=current_datetime,
        )

        return create_agent(
            model=self.llm,
            system_prompt=coordinator_prompt,
            tools=[think],  # task() injected by SubAgentMiddleware
            middleware=coordinator_middleware,
            state_schema=DeepResearchAgentState,
        ).with_config({"recursion_limit": 500})

    async def run(self, query: str) -> str:
        """Run the researcher and return a unified research brief.

        Args:
            query: A focused research brief describing what to investigate.

        Returns:
            Synthesized research brief with inline citations and Sources section.
        """
        if len(query.strip()) < 4:
            return "Research query is too short / not specific enough. Please provide a more detailed research brief."

        logger.info("ResearcherAgent: Starting research for: %s...", query[:100])

        state = DeepResearchAgentState(messages=[HumanMessage(content=query)])
        _timeout = self.timeout if self.timeout > 0 else None
        _config = {"callbacks": self.callbacks} if self.callbacks else None

        try:
            result = await asyncio.wait_for(
                self._agent.ainvoke(state, config=_config),
                timeout=_timeout,
            )

            if result and result.get("messages"):
                final_content = result["messages"][-1].content
                brief = final_content if isinstance(final_content, str) else str(final_content)
                logger.info("ResearcherAgent: Research complete (%d chars)", len(brief))
                return brief

            logger.warning("ResearcherAgent: No messages in result")
            return "Research produced no output."

        except TimeoutError:
            logger.warning(
                "ResearcherAgent timed out after %ss for query: %s...",
                self.timeout,
                query[:100],
            )
            return (
                f"[Research timed out after {self.timeout}s] "
                "The researcher could not complete within the time budget. "
                "Partial findings were not recoverable. "
                "The orchestrator should proceed with information already gathered from other sources."
            )

        except Exception as ex:
            logger.error("ResearcherAgent failed: %s", ex, exc_info=True)
            raise
