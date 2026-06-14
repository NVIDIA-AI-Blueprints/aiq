# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Internal report rewriter agent."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from .models import ReportRewriterAgentState

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).parent
ORIGINAL_REPORT_PATH = "/shared/original_report.md"
SOURCE_SUMMARY_PATH = "/shared/source_summary.md"
PARENT_CONTEXT_PATH = "/shared/parent_report_context.json"
EDIT_INSTRUCTION_PATH = "/shared/edit_instruction.txt"
OUTPUT_REPORT_PATH = "/shared/output.md"


class ReportRewriterAgent:
    """Rewrite a completed parent report into a full revised child report."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool] | None = None,
        *,
        verbose: bool = False,
        callbacks: list[Any] | None = None,
        config: Any | None = None,
        job_id: str | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.tools = list(tools or [])
        self.verbose = verbose
        self.callbacks = callbacks or []
        self.config = config
        self.job_id = job_id
        self.system_prompt = load_prompt(AGENT_DIR / "prompts", "edit")

    @staticmethod
    def _read_text_file(files: dict[str, Any], path: str) -> str | None:
        value = files.get(path)
        if isinstance(value, dict):
            value = value.get("content")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _latest_user_message(state: ReportRewriterAgentState) -> str:
        for message in reversed(state.messages):
            if isinstance(message, HumanMessage):
                content = message.content
                return content if isinstance(content, str) else str(content)
        return ""

    async def run(self, state: ReportRewriterAgentState) -> ReportRewriterAgentState:
        original_report = self._read_text_file(state.files, ORIGINAL_REPORT_PATH)
        if original_report is None:
            raise ValueError(f"Report rewrite requires {ORIGINAL_REPORT_PATH}")

        instruction = self._read_text_file(state.files, EDIT_INSTRUCTION_PATH) or self._latest_user_message(state)
        if not instruction.strip():
            raise ValueError("Report rewrite requires a non-empty edit instruction")

        source_summary = self._read_text_file(state.files, SOURCE_SUMMARY_PATH) or (
            "No durable source metadata was found for the parent report."
        )
        parent_context = self._read_text_file(state.files, PARENT_CONTEXT_PATH) or "{}"

        rendered_prompt = render_prompt_template(
            self.system_prompt,
            original_report=original_report,
            source_summary=source_summary,
            parent_context=parent_context,
            edit_instruction=instruction.strip(),
        )

        response = await self.llm_provider.get(LLMRole.REPORT_WRITER).ainvoke(
            [
                SystemMessage(content=rendered_prompt),
                HumanMessage(content=instruction.strip()),
            ]
        )
        revised_report = response.content if hasattr(response, "content") else str(response)
        revised_report = revised_report if isinstance(revised_report, str) else str(revised_report)
        revised_report = revised_report.strip()
        if not revised_report:
            raise ValueError("Report writer returned an empty revised report")

        for callback in self.callbacks:
            if hasattr(callback, "emit_final_report"):
                callback.emit_final_report(revised_report)
                break

        files = dict(state.files)
        files[OUTPUT_REPORT_PATH] = revised_report
        logger.info("Report rewrite complete (job_id=%s, chars=%d)", self.job_id, len(revised_report))
        return ReportRewriterAgentState(
            messages=[*state.messages, AIMessage(content=revised_report)],
            files=files,
        )
