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

"""Intent classifier agent for classifying meta vs research queries."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import SystemMessage

from aiq_agent.common import extract_json
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from ..models import ChatResearcherState
from ..models import DepthDecision
from ..models import IntentResult
from ..utils import trim_message_history

logger = logging.getLogger(__name__)


_LLM_UNAVAILABLE_MESSAGE = (
    "I'm unable to reach the model service right now. "
    "Please check your LLM API key and that the configured model is available for your account."
)
_LLM_TIMEOUT_MESSAGE = "The model service took too long to respond and the request timed out. "


def _is_llm_api_unavailable(err: BaseException) -> bool:
    """True if the error is from the LLM API being unreachable (e.g. 404, function not found)."""
    msg = str(err).strip()
    return (
        "[404]" in msg
        or "not found for account" in msg.lower()
        or (msg.lower().startswith("not found") and "account" in msg.lower())
    )


def _is_timeout_error(err: BaseException) -> bool:
    """True if the error is from a timeout (asyncio.wait_for or gateway 504)."""
    if isinstance(err, TimeoutError | asyncio.TimeoutError):
        return True
    msg = str(err).strip().lower()
    return "504" in msg or "gateway time-out" in msg or "gateway timeout" in msg


class IntentClassifier:
    def __init__(
        self,
        llm: BaseChatModel,
        tools_info: list[dict[str, str]] | None = None,
        prompt: str | None = None,
        callbacks: list[BaseCallbackHandler] | None = None,
        max_history: int = 20,
        llm_timeout: float = 90,
    ) -> None:
        self.llm = llm
        self.tools_info = tools_info or []
        self.prompt = prompt or self._load_default_prompt()
        self.callbacks = callbacks or []
        self.max_history = max_history
        self.llm_timeout = llm_timeout

    def _load_default_prompt(self) -> str:
        try:
            return load_prompt(Path(__file__).parent.parent / "prompts", "intent_classification.j2")
        except Exception:
            return (
                "/no_think\n\n"
                "You are an Orchestrator. Classify intent as 'meta' or 'research'.\n"
                "If meta, provide 'meta_response'. If research, provide 'research_depth'.\n"
                "Respond ONLY with JSON."
            )

    async def run(self, state: ChatResearcherState) -> dict[str, Any]:
        """Run the intent classifier node."""
        messages = state.messages
        if not messages:
            return {
                "user_intent": IntentResult(intent="research", raw=None),
                "depth_decision": DepthDecision(decision="deep", raw_reasoning="No query"),
            }

        user_info = state.user_info or {}
        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        last_content = messages[-1].content
        query = last_content if isinstance(last_content, str) else str(last_content or "")

        system_content = render_prompt_template(
            self.prompt,
            query=query,
            current_datetime=current_datetime,
            user_info=user_info,
            tools=self.tools_info,
        )
        trimmed_conversation = trim_message_history(list(state.messages), max_tokens=self.max_history)
        messages: list[BaseMessage] = [SystemMessage(content=system_content)] + trimmed_conversation

        try:
            config = {"callbacks": self.callbacks} if self.callbacks else {}
            response = await asyncio.wait_for(
                self.llm.ainvoke(messages, config=config),
                timeout=self.llm_timeout,
            )

            response_text = (response.content or "").strip()
            parsed = extract_json(response_text)

            if not parsed or not isinstance(parsed, dict):
                return {
                    "user_intent": IntentResult(intent="research", raw=None),
                    "depth_decision": DepthDecision(decision="shallow", raw_reasoning="Parse failed"),
                }

            raw_intent = (parsed.get("intent") or "research").strip().lower()
            intent = raw_intent if raw_intent in ("meta", "research") else "research"
            meta_response = parsed.get("meta_response")
            research_depth = (parsed.get("research_depth") or "shallow").strip().lower()
            depth_reasoning = parsed.get("depth_reasoning") or ""

            update: dict[str, Any] = {
                "user_intent": IntentResult(intent=intent, raw=parsed),
            }

            if intent == "meta":
                meta_text = (
                    meta_response if isinstance(meta_response, str) and meta_response.strip() else "I'm here to help."
                )
                update["messages"] = [AIMessage(content=meta_text)]
            else:
                update["depth_decision"] = DepthDecision(
                    decision=research_depth if research_depth in ("shallow", "deep") else "shallow",
                    raw_reasoning=str(depth_reasoning),
                )

            return update

        except TimeoutError:
            logger.warning(
                "LLM call timed out after %s seconds.",
                self.llm_timeout,
            )
            return {
                "user_intent": IntentResult(intent="meta", raw=None),
                "messages": [AIMessage(content=_LLM_TIMEOUT_MESSAGE)],
            }
        except Exception as e:
            if _is_llm_api_unavailable(e):
                logger.exception(
                    "LLM API unreachable (e.g. 404 model/function not found): %s.",
                    str(e).split("\n")[0],
                )
                return {
                    "user_intent": IntentResult(intent="meta", raw=None),
                    "messages": [AIMessage(content=_LLM_UNAVAILABLE_MESSAGE)],
                }
            if _is_timeout_error(e):
                logger.exception("LLM call failed with timeout (e.g. 504 Gateway Time-out): %s", e)
                return {
                    "user_intent": IntentResult(intent="meta", raw=None),
                    "messages": [AIMessage(content=_LLM_TIMEOUT_MESSAGE)],
                }
            logger.exception("Error in orchestration: %s", e)
            err_msg = "We couldn't process your request due to a temporary error. Please try again."
            return {
                "user_intent": IntentResult(intent="meta", raw=None),
                "messages": [AIMessage(content=err_msg)],
            }
