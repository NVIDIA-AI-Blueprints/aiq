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

"""State models for clarifier agent."""

from typing import Annotated
from typing import Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from pydantic import Field
from pydantic import computed_field


class ClarifierResult(BaseModel):
    """
    Result returned from clarifier agent run.

    Contains the clarification log plus optional plan approval details.
    """

    clarifier_log: str = Field(default="")
    plan_title: str | None = Field(default=None)
    plan_sections: list[str] = Field(default_factory=list)
    plan_approved: bool = Field(default=False)
    plan_rejected: bool = Field(default=False)

    def get_approved_plan_context(self) -> str | None:
        """Get formatted plan context if approved."""
        if not self.plan_approved or not self.plan_title:
            return None
        sections_text = "\n".join(f"- {s}" for s in self.plan_sections)
        return f"**Approved Research Plan**\n\nTitle: {self.plan_title}\n\nSections:\n{sections_text}"


class ClarifierAgentState(BaseModel):
    """
    State for clarifier agent.

    Attributes:
        messages: Conversation history with LangGraph message reducer.
        data_sources: Optional list of data sources to scope tools.
        available_documents: User-uploaded documents (file_name, summary) that are
            ingested; the user may refer to these.
        max_turns: Maximum number of turns for the clarification dialog.
        clarifier_log: Log of the clarification dialog.
        iteration: Current iteration of the clarification dialog.
        plan_title: Title of the generated research plan (if plan approval enabled).
        plan_sections: List of section titles for the research plan.
        plan_approved: Whether the user approved the plan.
        plan_rejected: Whether the user rejected the plan.
        plan_feedback_history: History of user feedback on plan iterations.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    data_sources: list[str] | None = Field(default=None)
    available_documents: list[dict[str, Any]] | None = Field(
        default=None,
        description="User-uploaded documents (file_name, summary) that are ingested; the user may refer to these.",
    )
    max_turns: int = Field(default=3)
    clarifier_log: str = Field(default="")
    iteration: int = Field(default=0)
    plan_title: str | None = Field(default=None)
    plan_sections: list[str] = Field(default_factory=list)
    plan_approved: bool = Field(default=False)
    plan_rejected: bool = Field(default=False)
    plan_feedback_history: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def remaining_questions(self) -> int:
        """Compute remaining clarification turns."""
        return self.max_turns - self.iteration
