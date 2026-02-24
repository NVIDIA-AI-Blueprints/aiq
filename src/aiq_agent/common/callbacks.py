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

import logging
import os
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


YELLOW = "\033[33m"
CYAN = "\033[36m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[39m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET_ALL = "\033[0m"


def is_verbose_enabled() -> bool:
    return os.environ.get("AIQ_VERBOSE", "").lower() in ("1", "true", "yes")


class ResearchLogger:
    """Colored logging utilities for research agents."""

    def __init__(self, logger_instance: logging.Logger, verbose: bool | None = None):
        self.logger = logger_instance
        self.verbose = verbose if verbose is not None else is_verbose_enabled()

    def section(self, label: str, message: str, *args):
        self.logger.info(f"{BOLD}[{label}]{RESET_ALL} {message}", *args)

    def success(self, label: str, message: str, *args):
        self.logger.info(f"{GREEN}[{label}]{RESET} {message}", *args)

    def info(self, label: str, message: str, *args):
        self.logger.info(f"{CYAN}[{label}]{RESET} {message}", *args)

    def detail(self, message: str, *args):
        if self.verbose:
            self.logger.info(f"{DIM}  {message}{RESET_ALL}", *args)

    def item(self, label: str, message: str, *args):
        self.logger.info(f"{MAGENTA}[{label}]{RESET} {message}", *args)

    def result(self, label: str, message: str, *args):
        self.logger.info(f"{GREEN}[{label}]{RESET} {message}", *args)

    def warning(self, label: str, message: str, *args):
        self.logger.warning(f"{YELLOW}[{label}]{RESET} {message}", *args)

    def error(self, label: str, message: str, *args):
        self.logger.error(f"{RED}[{label}]{RESET} {message}", *args)

    def skip(self, label: str, message: str, *args):
        self.logger.info(f"{DIM}[{label}]{RESET_ALL} {message}", *args)

    def query(self, query_id: str, query_text: str):
        self.logger.info(f"{MAGENTA}[Query]{RESET} {query_id}")
        if self.verbose:
            self.logger.info(f"{YELLOW}  Query: {query_text}{RESET}")

    def tool_call(self, tool_name: str, input_preview: str | None = None):
        self.logger.info(f"{GREEN}[Tool Call]{RESET} {tool_name}")
        if self.verbose and input_preview:
            self.logger.info(f"{DIM}  Input: {input_preview[:200]}{RESET_ALL}")

    def tool_result(self, tool_name: str, result_preview: str | None = None, chars: int | None = None):
        msg = f"{tool_name}: {chars} chars" if chars is not None else tool_name
        self.logger.info(f"{GREEN}[Tool Result]{RESET} {msg}")
        if self.verbose and result_preview:
            self.logger.debug(f"{DIM}  Result: {result_preview[:300]}{RESET_ALL}")

    def relevancy(self, relevant: int, total: int, reasoning: str | None = None):
        self.logger.info(f"{CYAN}[Relevancy]{RESET} {relevant}/{total} relevant")
        if self.verbose and reasoning:
            self.logger.info(f"{DIM}  Reasoning: {reasoning}{RESET_ALL}")

    def relevant_item(self, title: str, url: str | None = None):
        if self.verbose:
            self.logger.info(f"{GREEN}    [Relevant]{RESET} {title}")
            if url:
                self.logger.info(f"{DIM}      URL: {url}{RESET_ALL}")

    def banner(self, agent_name: str, query: str, **kwargs):
        self.logger.info("=" * 80)
        self.logger.info(f"{BOLD}[{agent_name}]{RESET_ALL} Starting research")
        self.logger.info(f"{YELLOW}Query:{RESET} {query[:100]}...")
        for key, value in kwargs.items():
            self.logger.info(f"{DIM}{key}: {value}{RESET_ALL}")
        self.logger.info("=" * 80)


class VerboseTraceCallback(BaseCallbackHandler):
    """Callback handler that logs detailed agent traces with live output."""

    def __init__(self, log_reasoning: bool = True, max_chars: int = 5000):
        self.log_reasoning = log_reasoning
        self.max_chars = max_chars
        self.current_input: str | None = None
        self.active_chains: dict[Any, str] = {}
        self.depth = 0

    def _get_indent(self) -> str:
        return "  " * self.depth

    def on_chain_start(self, serialized: dict | None, inputs: dict, **kwargs) -> None:
        run_id = kwargs.get("run_id")

        if serialized:
            chain_name = serialized.get("name") or (
                serialized.get("id", ["unknown"])[-1] if serialized.get("id") else "chain"
            )
        else:
            chain_name = kwargs.get("name", "chain")

        if run_id:
            self.active_chains[run_id] = chain_name
            self.depth += 1

        if inputs and "messages" in inputs:
            messages = inputs["messages"]
            if messages and hasattr(messages[-1], "content"):
                self.current_input = messages[-1].content

        if "subagent" in chain_name.lower() or "agent" in chain_name.lower():
            logger.info("%s%s[Chain Start] %s%s", self._get_indent(), CYAN, chain_name, RESET)

    def on_chain_end(self, outputs: dict, **kwargs) -> None:
        run_id = kwargs.get("run_id")
        if run_id and run_id in self.active_chains:
            chain_name = self.active_chains.pop(run_id)
            if "subagent" in chain_name.lower() or "agent" in chain_name.lower():
                logger.info("%s%s[Chain End] %s%s", self._get_indent(), CYAN, chain_name, RESET)
            self.depth = max(0, self.depth - 1)

    def on_llm_start(self, serialized: dict | None, prompts: list[str], **kwargs) -> None:
        if serialized:
            model_name = serialized.get("name") or (
                serialized.get("id", ["LLM"])[-1] if serialized.get("id") else "LLM"
            )
        else:
            model_name = kwargs.get("name", "LLM")

        print(flush=True)
        logger.info("-" * 30)
        logger.info("%s[AGENT]%s %s", BOLD, RESET_ALL, model_name)
        if self.current_input:
            preview = self.current_input[:200] + "..." if len(self.current_input) > 200 else self.current_input
            logger.info("%sAgent input: %s%s", YELLOW, preview, RESET)

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        if not response.generations:
            return

        generation = response.generations[0][0]
        message = generation.message if hasattr(generation, "message") else None

        if message:
            self._log_message_details(message)
        else:
            text = generation.text if hasattr(generation, "text") else str(generation)
            logger.info("%sAgent response: %s%s", CYAN, text[: self.max_chars], RESET)

        logger.info("-" * 30)
        print(flush=True)

    def _log_message_details(self, message: Any) -> None:
        reasoning_content = None
        if hasattr(message, "additional_kwargs"):
            reasoning_content = message.additional_kwargs.get("reasoning_content")

        if reasoning_content and self.log_reasoning:
            logger.info("%s[Reasoning]%s", MAGENTA, RESET_ALL)
            display = reasoning_content[: self.max_chars]
            if len(reasoning_content) > self.max_chars:
                display += f"... [truncated, {len(reasoning_content)} total chars]"
            logger.info("%s%s%s", DIM, display, RESET_ALL)

        content = getattr(message, "content", "")
        if content:
            logger.info("%s[Agent Response]%s", CYAN, RESET)
            display = content[: self.max_chars]
            if len(content) > self.max_chars:
                display += f"... [truncated, {len(content)} total chars]"
            logger.info("%s%s%s", CYAN, display, RESET)

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            logger.info("%s[Tool Calls] %d tool(s) requested%s", GREEN, len(tool_calls), RESET)
            for tc in tool_calls:
                tool_name = tc.get("name", "unknown")
                tool_args = tc.get("args", {})
                args_preview = str(tool_args)[:300]
                logger.info("%s  → %s%s", GREEN, tool_name, RESET)
                logger.info("%s    Args: %s%s", DIM, args_preview, RESET_ALL)

        if hasattr(message, "response_metadata"):
            metadata = message.response_metadata
            token_usage = metadata.get("token_usage", {})
            model_name = metadata.get("model_name", "unknown")
            if token_usage:
                logger.info(
                    "%s[Tokens] prompt=%s, completion=%s, model=%s%s",
                    DIM,
                    token_usage.get("prompt_tokens", "N/A"),
                    token_usage.get("completion_tokens", "N/A"),
                    model_name,
                    RESET_ALL,
                )

    def on_tool_start(self, serialized: dict | None, input_str: str, **kwargs) -> None:
        tool_name = serialized.get("name", "unknown") if serialized else kwargs.get("name", "unknown")
        logger.info("%s[Tool Start] %s%s", GREEN, tool_name, RESET)
        preview = input_str[:500] + "..." if len(input_str) > 500 else input_str
        logger.info("%s  Input: %s%s", DIM, preview, RESET_ALL)

    def on_tool_end(self, output: str, **kwargs) -> None:
        output_str = str(output)
        preview = output_str[:1000] + f"... [{len(output_str)} chars total]" if len(output_str) > 1000 else output_str
        logger.info("%s[Tool Result] %s%s", GREEN, preview, RESET)

    def on_tool_error(self, error: Exception, **kwargs) -> None:
        logger.error("%s[Tool Error] %s%s", RED, error, RESET)

    def on_agent_action(self, action: Any, **kwargs) -> None:
        tool_name = getattr(action, "tool", "unknown")
        tool_input = getattr(action, "tool_input", {})
        logger.info("%s[Agent Action] Delegating to: %s%s", MAGENTA, tool_name, RESET)
        if isinstance(tool_input, dict) and "messages" in tool_input:
            msg_content = tool_input["messages"][-1].content if tool_input["messages"] else ""
            preview = msg_content[:200] + "..." if len(msg_content) > 200 else msg_content
            logger.info("%s  Task: %s%s", DIM, preview, RESET_ALL)

    def on_agent_finish(self, finish: Any, **kwargs) -> None:
        output = getattr(finish, "return_values", {})
        if output:
            output_str = str(output)[:500]
            logger.info("%s[Agent Finish] %s%s", GREEN, output_str, RESET)
