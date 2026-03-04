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

"""Planner agent implementation with scout + architect sub-agents."""

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
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from ..custom_middleware import EmptyContentFixMiddleware
from ..custom_middleware import EmptyResponseRetryMiddleware
from ..custom_middleware import TodoSanitizationMiddleware
from ..custom_middleware import ToolCallBudgetMiddleware
from ..custom_middleware import ToolNameSanitizationMiddleware
from ..models import DeepResearchAgentState

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).parent

# Middleware tool names (injected by TodoListMiddleware etc.)
_MIDDLEWARE_TOOL_NAMES = ["write_todos"]

# Budget constants
_COORDINATOR_TOOL_BUDGET = 8  # scout + architect + think calls
_SCOUT_TOOL_BUDGET = 32  # 10-15 broad searches + think
_ARCHITECT_TOOL_BUDGET = 32  # 8-12 targeted searches + think


@tool
def think(thought: str) -> str:
    """Use this tool to reason through complex decisions, verify constraints, or
    plan next steps before acting. The tool records your thought without taking
    any action or retrieving new information.

    Args:
        thought: Your reasoning, analysis, or verification to record.
    """
    logger.info("Planner thinking: %s", thought[:200])
    return "Thought recorded."


class PlannerAgentImpl:
    """Two-phase planner agent: scout discovers the landscape, architect designs the structure.

    The planner coordinator runs sequentially:
    1. Calls scout with the user's request → landscape report
    2. Reviews scout output with think
    3. Calls architect with full scout output + review notes → final plan
    4. Validates and returns the plan JSON
    """

    def __init__(
        self,
        llm: Any,
        tools: Sequence[BaseTool] | None = None,
        *,
        verbose: bool = True,
        callbacks: list[Any] | None = None,
        timeout: int = 1800,
    ) -> None:
        self.llm = llm
        self.tools = list(tools) if tools else []
        self.callbacks = callbacks or []
        self.timeout = timeout

        self._prompts = self._load_prompts()
        self.tools_info = [{"name": t.name, "description": t.description} for t in self.tools]
        self.all_tools = [think, *self.tools]

        self._agent = self._build_agent()

    def _load_prompts(self) -> dict[str, str]:
        """Load all prompts for planner sub-agents."""
        prompts = {}
        prompt_names = ["planner_coordinator", "scout", "architect"]
        for name in prompt_names:
            try:
                prompts[name] = load_prompt(AGENT_DIR / "prompts", name)
            except Exception as e:
                logger.warning("Failed to load prompt %s: %s", name, e)
                prompts[name] = f"You are a {name} agent. Complete the task described."
        return prompts

    def _build_agent(self):
        """Build the planner coordinator agent with scout + architect sub-agents."""
        current_datetime = datetime.now().strftime("%Y-%m-%d")

        # Define sub-agents
        subagents = [
            {
                "name": "scout",
                "description": (
                    "Landscape discovery — broad searches to map what information exists, "
                    "discover what terms mean in practice, surface hidden assumptions, "
                    "and identify where sources disagree."
                ),
                "system_prompt": render_prompt_template(
                    self._prompts["scout"],
                    current_datetime=current_datetime,
                    tools=self.tools_info,
                ),
                "tools": self.all_tools,
                "model": self.llm,
                "middleware": [ToolCallBudgetMiddleware(max_tool_calls=_SCOUT_TOOL_BUDGET)],
            },
            {
                "name": "architect",
                "description": (
                    "Structure design — given the scout's landscape findings, produces "
                    "a detailed TOC, generates research briefs for downstream researchers, "
                    "creates depth and breadth targets, and defines quality constraints."
                ),
                "system_prompt": render_prompt_template(
                    self._prompts["architect"],
                    current_datetime=current_datetime,
                    tools=self.tools_info,
                ),
                "tools": self.all_tools,
                "model": self.llm,
                "middleware": [ToolCallBudgetMiddleware(max_tool_calls=_ARCHITECT_TOOL_BUDGET)],
            },
        ]

        # Sub-agent default middleware (applied by SubAgentMiddleware to SubAgent dicts)
        subagent_middleware = [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(valid_tool_names=[t.name for t in self.all_tools] + _MIDDLEWARE_TOOL_NAMES),
            TodoSanitizationMiddleware(),
            EmptyResponseRetryMiddleware(min_content_length=512, max_retries=2),
            ModelRetryMiddleware(max_retries=10, backoff_factor=2.0, initial_delay=1.0),
        ]

        # Coordinator middleware
        coordinator_middleware = [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(
                valid_tool_names=[t.name for t in [think]] + _MIDDLEWARE_TOOL_NAMES + ["task"],
                task_subagent_default="scout",
            ),
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
        ]

        coordinator_prompt = render_prompt_template(
            self._prompts["planner_coordinator"],
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
        """Run the planner and return the plan as a JSON string.

        Args:
            query: The user's research request.

        Returns:
            Plan JSON string with task_analysis, report_title, report_toc,
            constraints, and queries.
        """
        logger.info("PlannerAgent: Starting planning for query: %s...", query[:100])

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
                plan_text = final_content if isinstance(final_content, str) else str(final_content)
                logger.info("PlannerAgent: Plan complete (%d chars)", len(plan_text))
                return plan_text

            logger.warning("PlannerAgent: No messages in result")
            return '{"error": "Planner produced no output"}'

        except TimeoutError:
            logger.warning(
                "PlannerAgent timed out after %ss for query: %s...",
                self.timeout,
                query[:100],
            )
            return '{"error": "Planner timed out", "fallback": true, "message": "Planning phase exceeded time budget."}'

        except Exception as ex:
            logger.error("PlannerAgent failed: %s", ex, exc_info=True)
            raise
