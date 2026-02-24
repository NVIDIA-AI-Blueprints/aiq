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

"""State models for chat researcher agent."""

from typing import Annotated
from typing import Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from aiq_agent.knowledge import AvailableDocument

from .depth import DepthDecision
from .intent import IntentResult
from .result import ShallowResult


class ChatResearcherState(BaseModel):
    """
    State for the main chat researcher workflow graph.

    Attributes:
        messages: Conversation history with LangGraph message reducer.
        tools_info: Information about available tools.
        user_info: Optional user information for personalization.
        data_sources: Optional list of user-selected data source IDs.
        user_intent: Result of intent classification.
        depth_decision: Result of depth routing.
        final_report: The final research report.
        shallow_result: Result from shallow research (if executed).
        clarifier_result: Log from clarifier agent dialog.
        original_query: The latest user query, preserved for deep research.
        available_documents: User-uploaded documents with summaries for context.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    user_info: dict[str, Any] | None = None
    data_sources: list[str] | None = None
    user_intent: IntentResult | None = None
    depth_decision: DepthDecision | None = None
    final_report: str | None = None
    shallow_result: ShallowResult | None = None
    clarifier_result: str | None = None
    original_query: str | None = None
    available_documents: list[AvailableDocument] | None = None
