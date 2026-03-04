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

"""Custom middleware for the deep research agent."""

import json
import logging
from difflib import get_close_matches

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


class EmptyContentFixMiddleware(AgentMiddleware):
    """
    Middleware that fixes empty ToolMessage content.

    Some LLM APIs (e.g., NVIDIA, OpenAI) reject messages with empty content.
    This middleware ensures all ToolMessages have non-empty content by
    replacing empty strings with a placeholder.
    """

    def __init__(self, placeholder: str = "empty content received."):
        """
        Initialize the middleware.

        Args:
            placeholder: Text to use when ToolMessage content is empty.
        """
        self.placeholder = placeholder

    async def awrap_model_call(self, request, handler):
        """Fix empty ToolMessage content before sending to the model."""
        fixed_messages = []
        for msg in request.messages:
            if isinstance(msg, ToolMessage) and not msg.content:
                # Create a new ToolMessage with placeholder content
                fixed_messages.append(
                    ToolMessage(
                        content=self.placeholder,
                        tool_call_id=msg.tool_call_id,
                        name=getattr(msg, "name", None),
                        id=msg.id,
                    )
                )
            else:
                fixed_messages.append(msg)

        return await handler(request.override(messages=fixed_messages))


# Parameter name aliases: keys are substrings matched against tool names
_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "search": {"question": "query"},  # Any tool with "search" in the name
}

# Common hallucinated tool name mappings
_TOOL_NAME_ALIASES: dict[str, str] = {
    "open_file": "read_file",
    "find": "grep",
    "find_file": "glob",  # Claude Opus 4.6 hallucinations — advanced_web_search_tool
    "advance_web_search_tool": "advanced_web_search_tool",
    "web_search": "advanced_web_search_tool",
    "search_web": "advanced_web_search_tool",
    "core_web_search": "advanced_web_search_tool",
    "search": "advanced_web_search_tool",  # Ensemble web search aliases (valid_tool_names check picks the right target)
    "ensemble_search": "ensemble_web_search_tool",
    "ensemble_web_search": "ensemble_web_search_tool",
    "ensemble_search_tool": "ensemble_web_search_tool",  # Common typo hallucinations
    "todos": "write_todos",
    "tink": "think",
}


class ToolNameSanitizationMiddleware(AgentMiddleware):
    """
    Middleware that sanitizes corrupted tool names in LLM responses.

    LLMs sometimes generate malformed tool calls with suffixes like
    <|channel|>commentary or .exec, or hallucinate tool names like
    open_file or find. This middleware intercepts the model response
    and fixes tool names before the framework dispatches them.
    """

    def __init__(
        self,
        valid_tool_names: list[str],
        task_subagent_default: str | None = None,
        valid_subagent_types: set[str] | None = None,
    ):
        self.valid_tool_names = set(valid_tool_names)
        self.task_subagent_default = task_subagent_default
        self.valid_subagent_types = valid_subagent_types

    def _sanitize_tool_name(self, name: str) -> str:
        """Sanitize a potentially corrupted tool name.

        Returns the cleaned name if it maps to a valid tool,
        otherwise returns the original name unchanged.
        """
        # 0. Convert kebab-case to snake_case if the result is valid
        if "-" in name:
            candidate = name.replace("-", "_")
            if candidate in self.valid_tool_names:
                logger.info("Sanitized kebab-case tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 1. Strip <|channel|> and everything after
        if "<|channel|>" in name:
            candidate = name.split("<|channel|>", maxsplit=1)[0]
            if candidate in self.valid_tool_names:
                logger.info("Sanitized tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 2. Strip dot suffix if base name is valid
        if "." in name:
            candidate = name.split(".", maxsplit=1)[0]
            if candidate in self.valid_tool_names:
                logger.info("Sanitized tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 3. Map common hallucinated names
        if name in _TOOL_NAME_ALIASES:
            mapped = _TOOL_NAME_ALIASES[name]
            if mapped in self.valid_tool_names:
                logger.info("Mapped tool name: '%s' -> '%s'", name, mapped)
                return mapped

        return name

    def _sanitize_tool_args(self, tool_name: str, args: dict) -> dict:
        """Fix common parameter name mistakes based on tool name patterns."""
        for pattern, aliases in _PARAM_ALIASES.items():
            if pattern in tool_name:
                for wrong_name, right_name in aliases.items():
                    if wrong_name in args and right_name not in args:
                        args = {right_name if k == wrong_name else k: v for k, v in args.items()}
                        logger.info("Sanitized param name in '%s': '%s' -> '%s'", tool_name, wrong_name, right_name)

        # Fix missing subagent_type in task() calls
        if tool_name == "task" and "subagent_type" not in args and self.task_subagent_default:
            logger.info("Injected default subagent_type '%s' for task() call", self.task_subagent_default)
            args = {**args, "subagent_type": self.task_subagent_default}

        # Validate subagent_type against known types
        if tool_name == "task" and self.valid_subagent_types and "subagent_type" in args:
            subagent_type = args["subagent_type"]
            if subagent_type not in self.valid_subagent_types:
                matches = get_close_matches(subagent_type, list(self.valid_subagent_types), n=1, cutoff=0.6)
                if matches:
                    logger.info("Fuzzy-matched subagent_type: '%s' -> '%s'", subagent_type, matches[0])
                    args = {**args, "subagent_type": matches[0]}
                elif self.task_subagent_default:
                    logger.warning(
                        "Unknown subagent_type '%s', falling back to '%s'", subagent_type, self.task_subagent_default
                    )
                    args = {**args, "subagent_type": self.task_subagent_default}

        return args

    async def awrap_tool_call(self, request, handler):
        """Block task() calls with empty or bare descriptions."""
        tc = request.tool_call
        if tc["name"] == "task" and self.valid_subagent_types:
            desc = tc["args"].get("description", "").strip()
            if len(desc) < 16 or desc.lower() in self.valid_subagent_types:
                logger.warning(
                    "Blocked bare task() dispatch: description='%s' (%d chars)",
                    desc[:50],
                    len(desc),
                )
                return ToolMessage(
                    content=(
                        "Dispatch blocked: description is too short or is just the role name. "
                        "Provide a detailed description including the specific research question, "
                        "expected depth, and relevant context from the brief."
                    ),
                    tool_call_id=tc["id"],
                    name="task",
                    status="error",
                )
        return await handler(request)

    async def awrap_model_call(self, request, handler):
        """Intercept model response and sanitize tool names and args."""
        response = await handler(request)

        needs_fix = False
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if self._sanitize_tool_name(tc["name"]) != tc["name"]:
                        needs_fix = True
                        break
                    sanitized_name = self._sanitize_tool_name(tc["name"])
                    if self._sanitize_tool_args(sanitized_name, tc["args"]) != tc["args"]:
                        needs_fix = True
                        break
                if needs_fix:
                    break

        if not needs_fix:
            return response

        new_result = []
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                new_tool_calls = []
                for tc in msg.tool_calls:
                    sanitized_name = self._sanitize_tool_name(tc["name"])
                    sanitized_args = self._sanitize_tool_args(sanitized_name, tc["args"])
                    new_tool_calls.append({**tc, "name": sanitized_name, "args": sanitized_args})
                new_msg = AIMessage(
                    content=msg.content,
                    tool_calls=new_tool_calls,
                    id=msg.id,
                )
                new_result.append(new_msg)
            else:
                new_result.append(msg)

        return ModelResponse(result=new_result, structured_response=response.structured_response)


# Fuzzy status value mapping for write_todos
_STATUS_ALIASES: dict[str, str] = {
    "complete": "completed",
    "done": "completed",
    "finished": "completed",
    "progress": "in_progress",
    "in progress": "in_progress",
    "partial": "in_progress",
    "todo": "pending",
    "not_started": "pending",
}


class TodoSanitizationMiddleware(AgentMiddleware):
    """Middleware that fixes malformed write_todos arguments before Pydantic validation.

    Handles: wrong status enum values, missing/wrong field names,
    JSON string instead of list, and extra fields.
    """

    def _sanitize_todo_item(self, item: dict) -> dict:
        """Fix a single todo item."""
        fixed = {}

        # Map 'context' → 'content'
        if "context" in item and "content" not in item:
            fixed["content"] = item["context"]
        elif "content" in item:
            fixed["content"] = item["content"]
        else:
            fixed["content"] = str(item.get("text", item.get("description", "untitled task")))

        # Fix status enum
        raw_status = str(item.get("status", "pending")).lower().strip()
        fixed["status"] = _STATUS_ALIASES.get(raw_status, raw_status)
        # If still invalid after alias lookup, default to pending
        if fixed["status"] not in ("pending", "in_progress", "completed"):
            logger.info("Invalid todo status '%s', defaulting to 'pending'", raw_status)
            fixed["status"] = "pending"

        return fixed

    def _sanitize_todos_args(self, args: dict) -> dict:
        """Fix write_todos arguments."""
        todos = args.get("todos")
        if todos is None:
            return args

        # Handle JSON string instead of list
        if isinstance(todos, str):
            try:
                # Strip any channel markers that leaked in
                cleaned = todos.split("<|")[0] if "<|" in todos else todos
                todos = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Could not parse write_todos string arg")
                return args

        if not isinstance(todos, list):
            return args

        fixed_todos = [self._sanitize_todo_item(item) for item in todos if isinstance(item, dict)]
        return {**args, "todos": fixed_todos}

    async def awrap_model_call(self, request, handler):
        """Intercept model response and sanitize write_todos args."""
        response = await handler(request)

        needs_fix = False
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] == "write_todos":
                        needs_fix = True
                        break

        if not needs_fix:
            return response

        new_result = []
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                new_tool_calls = []
                for tc in msg.tool_calls:
                    if tc["name"] == "write_todos":
                        new_tool_calls.append({**tc, "args": self._sanitize_todos_args(tc["args"])})
                    else:
                        new_tool_calls.append(tc)
                new_msg = AIMessage(content=msg.content, tool_calls=new_tool_calls, id=msg.id)
                new_result.append(new_msg)
            else:
                new_result.append(msg)

        return ModelResponse(result=new_result, structured_response=response.structured_response)


class ToolCallBudgetMiddleware(AgentMiddleware):
    """Middleware that enforces a hard cap on total tool calls per agent run.

    2 states:
    1. NORMAL (used <= max): pass through — even if the response crosses the
       budget, let it execute. The model naturally gets one extra batch.
    2. EXHAUSTED (used > max): prepend HumanMessage nudge requesting synthesis.
       If the model still tries tool calls, retry with tools=[] so the model
       is forced to produce a text-only synthesis response.

    Stateless: counts tool calls already executed by counting ToolMessages in
    the request history. Each subagent starts with a fresh message list, so a
    single instance can be safely shared across subagents.
    """

    _BUDGET_EXHAUSTED_HUMAN_MSG = (
        "[SYSTEM: Your tool budget for this task is exhausted. "
        "You cannot make any more tool calls. Synthesize your findings from the "
        "work you already completed and return your final response now. "
        "The parent orchestrator still has full tool access and will continue the workflow.]"
    )

    def __init__(self, max_tool_calls: int = 32):
        self.max_tool_calls = max_tool_calls

    async def awrap_model_call(self, request, handler):
        used = sum(1 for msg in request.messages if isinstance(msg, ToolMessage))

        # Budget exhausted: nudge model to synthesize.
        if used > self.max_tool_calls:
            logger.info("Tool call budget: synthesis turn (%d/%d used)", used, self.max_tool_calls)
            nudge = HumanMessage(content=self._BUDGET_EXHAUSTED_HUMAN_MSG)
            response = await handler(request.override(messages=[*request.messages, nudge]))
            # If model still tries tool calls, retry with tools removed entirely.
            # tools=[] is safe: LangChain factory omits the tools param from the
            # API request when the list is empty (falsy check in _get_bound_model).
            for msg in response.result:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    logger.warning(
                        "Tool call budget: model ignored nudge, retrying without tools (%d/%d)",
                        used,
                        self.max_tool_calls,
                    )
                    return await handler(
                        request.override(
                            messages=[*request.messages, nudge],
                            tools=[],
                            tool_choice=None,
                        )
                    )
            return response

        # Normal: pass through (even if response crosses budget).
        return await handler(request)


class EmptyResponseRetryMiddleware(AgentMiddleware):
    """Middleware that retries when the model returns an empty response with no tool calls.

    Some LLMs may return AIMessages with empty
    content and no tool calls, which terminates the agent loop prematurely.
    This middleware detects that case and retries with a HumanMessage nudge
    telling the model what went wrong and how to proceed.

    TODO: Note on thinking tokens: each retry is a fresh LLM API call. The model's
    previous response (including any reasoning tokens) will likely be discarded —
    it is not included in the retry request. The nudge gives the model context
    about what happened so the retry is more likely to succeed than a blind replay.
    """

    _RETRY_NUDGE = (
        "Your previous response was {length} characters with no tool calls. "
        "This is too short to be useful. Either continue your work by making tool calls "
        "to gather more information, or write a complete, substantive response with your findings."
    )

    def __init__(
        self,
        min_content_length: int = 100,
        max_retries: int = 3,
    ):
        self.min_content_length = min_content_length
        self.max_retries = max_retries

    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        for attempt in range(self.max_retries):
            if not self._is_empty_terminal_response(response):
                break

            if self._has_reasoning(response):
                # The model produced reasoning (chain-of-thought) but no visible content.
                # This is a "thinking step" from models with enable_thinking=true.
                # Instead of dropping the reasoning with a nudge, append the model's
                # response to the history so it can see its own thinking and continue.
                logger.info(
                    "Model produced reasoning-only response (no content, no tool calls, attempt %d/%d) — "
                    "preserving reasoning and retrying",
                    attempt + 1,
                    self.max_retries,
                )
                modified = request.override(
                    messages=[*request.messages, *response.result],
                )
            else:
                # Truly empty — no reasoning, no content, no tool calls.
                content_length = self._get_content_length(response)
                logger.warning(
                    "Model returned empty response (%d chars, no tool calls, retry %d/%d)",
                    content_length,
                    attempt + 1,
                    self.max_retries,
                )
                nudge = HumanMessage(content=self._RETRY_NUDGE.format(length=content_length))
                modified = request.override(messages=[*request.messages, nudge])

            response = await handler(modified)
        return response

    def _is_empty_terminal_response(self, response: ModelResponse) -> bool:
        """Check if the response is an empty AIMessage with no tool calls."""
        if not response.result:
            return True
        last_msg = response.result[-1]
        if not isinstance(last_msg, AIMessage):
            return False
        last_content = last_msg.content or ""
        has_content = bool(len(str(last_content).strip()) >= self.min_content_length)
        has_tool_calls = bool(last_msg.tool_calls)
        return not has_tool_calls and not has_content

    def _has_reasoning(self, response: ModelResponse) -> bool:
        """Check if the response has reasoning_content (chain-of-thought from thinking models)."""
        if not response.result:
            return False
        last_msg = response.result[-1]
        if not isinstance(last_msg, AIMessage):
            return False
        return bool(last_msg.additional_kwargs.get("reasoning_content"))

    @staticmethod
    def _get_content_length(response: ModelResponse) -> int:
        """Get the content length of the last message in the response."""
        if not response.result:
            return 0
        last_msg = response.result[-1]
        if not isinstance(last_msg, AIMessage):
            return 0
        return len(str(last_msg.content or "").strip())


class ReportValidationMiddleware(AgentMiddleware):
    """Validates terminal responses as complete reports. Retries with a
    continuation nudge if the response is too short or lacks structure.

    Only fires on terminal responses (no tool calls). If the model makes
    tool calls on retry, those flow back to the agent loop normally.
    """

    _NUDGE = "Continue with the research workflow. You have not completed the task yet."

    def __init__(self, min_length: int = 5000, min_sections: int = 2, max_retries: int = 2):
        self.min_length = min_length
        self.min_sections = min_sections
        self.max_retries = max_retries

    def _is_incomplete_report(self, response: ModelResponse) -> tuple[bool, str]:
        if not response.result:
            return False, ""
        last_msg = response.result[-1]
        if not isinstance(last_msg, AIMessage):
            return False, ""
        if last_msg.tool_calls:
            return False, ""  # not terminal — skip

        content = str(last_msg.content or "")
        if len(content) < self.min_length:
            return True, f"too_short ({len(content)} chars)"
        if content.count("## ") < self.min_sections:
            return True, f"missing_sections ({content.count('## ')} found)"
        return False, ""

    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        for attempt in range(self.max_retries):
            incomplete, reason = self._is_incomplete_report(response)
            if not incomplete:
                break
            logger.warning("Report incomplete (retry %d/%d): %s", attempt + 1, self.max_retries, reason)
            nudge = HumanMessage(content=self._NUDGE)
            modified = request.override(messages=[*request.messages, nudge])
            response = await handler(modified)
        return response


class RewriterMiddleware(AgentMiddleware):
    """Refines terminal responses using an LLM that cross-checks against evidence.

    Intercepts the final response, extracts evidence ToolMessages
    from the message history, and sends {evidence + response} to a rewriter LLM
    for refinement in a fresh context window.
    """

    def __init__(self, model: BaseChatModel, prompt: str, tool_names: list[str]):
        self.model = model
        self.prompt = prompt
        self.tool_names = tool_names

    def _is_terminal(self, response: ModelResponse) -> bool:
        """Check if the response is a terminal text response (no tool calls)."""
        if not response.result:
            return False
        last_msg = response.result[-1]
        return isinstance(last_msg, AIMessage) and not last_msg.tool_calls

    def _extract_evidence(self, messages: list) -> tuple[str, list[str]]:
        """Extract the original user question and evidence texts from the message history.

        Returns:
            (user_question, evidence_texts) where user_question is the first HumanMessage
            content and evidence_texts are ToolMessages matching configured tool names.
        """
        user_question = ""
        evidence = []
        for msg in messages:
            if isinstance(msg, HumanMessage) and not user_question:
                user_question = str(msg.content or "")
            elif isinstance(msg, ToolMessage) and msg.name in self.tool_names:
                evidence.append(f"## {msg.name} output:\n{msg.content}")
        return user_question, evidence

    async def awrap_model_call(self, request, handler):
        response = await handler(request)

        if not self._is_terminal(response):
            return response

        original_content = str(response.result[-1].content or "")

        user_question, evidence_texts = self._extract_evidence(request.messages)
        if not evidence_texts:
            return response  # No evidence to cross-check against

        try:
            rewriter_input = f"<user_request>\n{user_question}\n</user_request>\n\n" if user_question else ""
            rewriter_input += f"<evidence>\n{'---'.join(evidence_texts)}\n</evidence>\n\n"
            rewriter_input += f"<original_output>\n{original_content}\n</original_output>"

            rewriter_messages = [
                SystemMessage(content=self.prompt),
                HumanMessage(content=rewriter_input),
            ]
            rewritten = await self.model.ainvoke(rewriter_messages)
            rewritten_content = str(rewritten.content or "").strip()

            # Fallback: if rewrite is empty or suspiciously short, keep original
            if len(rewritten_content) < len(original_content) * 0.9:
                logger.warning(
                    "RewriterMiddleware: rewritten content too short (%d vs %d chars), keeping original",
                    len(rewritten_content),
                    len(original_content),
                )
                return response

            delta_pct = (
                int((len(rewritten_content) - len(original_content)) / len(original_content) * 100)
                if original_content
                else 0
            )
            logger.info(
                "RewriterMiddleware: refined %d → %d chars (%+d%%)",
                len(original_content),
                len(rewritten_content),
                delta_pct,
            )

            # Replace the last message content with the rewritten version
            original_msg = response.result[-1]
            new_msg = AIMessage(content=rewritten_content, id=original_msg.id)
            new_result = list(response.result[:-1]) + [new_msg]
            return ModelResponse(result=new_result, structured_response=response.structured_response)

        except Exception as e:
            logger.warning("RewriterMiddleware: rewrite failed (%s), keeping original", e)
            return response
