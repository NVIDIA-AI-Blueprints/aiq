# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""AI-Q telemetry adapters for named LangChain agent spans."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from nat.data_models.intermediate_step import IntermediateStepPayload
from nat.data_models.intermediate_step import IntermediateStepType
from nat.data_models.intermediate_step import TraceMetadata
from nat.plugins.langchain.callback_handler import LangchainProfilerHandler


def _deepagents_agent_name(kwargs: dict[str, Any]) -> str | None:
    """Return the outer DeepAgents chain name, excluding internal graph nodes."""
    metadata = kwargs.get("metadata")
    if not isinstance(metadata, dict):
        return None

    semantic_name = metadata.get("lc_agent_name")
    callback_name = kwargs.get("name")
    if not isinstance(semantic_name, str) or callback_name != semantic_name:
        return None
    return semantic_name


def _task_display_name(serialized: dict[str, Any], input_str: str, inputs: dict[str, Any] | None) -> str:
    name = str(serialized.get("name", ""))
    if name != "task":
        return name

    parsed_inputs: Any = inputs
    if not isinstance(parsed_inputs, dict):
        try:
            parsed_inputs = ast.literal_eval(input_str)
        except (SyntaxError, ValueError):
            parsed_inputs = None
    subagent_type = parsed_inputs.get("subagent_type") if isinstance(parsed_inputs, dict) else None
    return f"task: {subagent_type}" if subagent_type else name


class AgentLifecycleTelemetryCallback(BaseCallbackHandler):
    """Emit named NAT agent spans while preserving the active task/tool stack."""

    run_inline = True

    def __init__(self, step_manager: Any) -> None:
        super().__init__()
        self._step_manager = step_manager
        self._agent_names: dict[str, str] = {}

    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: dict[str, Any], **kwargs: Any) -> None:
        name = _deepagents_agent_name(kwargs)
        run_id = str(kwargs.get("run_id", ""))
        if not run_id or name is None:
            return

        self._agent_names[run_id] = name
        parent_run_id = kwargs.get("parent_run_id")
        self._step_manager.push_intermediate_step(
            IntermediateStepPayload(
                UUID=run_id,
                event_type=IntermediateStepType.WORKFLOW_START,
                name=name,
                metadata=TraceMetadata(
                    provided_metadata={
                        "agent_id": run_id,
                        "agent_name": name,
                        "span_role": "agent",
                        "langchain_parent_run_id": str(parent_run_id) if parent_run_id else None,
                    }
                ),
            )
        )

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
        self._end_agent_run(outputs=outputs, error=None, **kwargs)

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        self._end_agent_run(outputs=None, error=error, **kwargs)

    def _end_agent_run(
        self,
        *,
        outputs: dict[str, Any] | None,
        error: BaseException | None,
        **kwargs: Any,
    ) -> None:
        run_id = str(kwargs.get("run_id", ""))
        name = self._agent_names.pop(run_id, None)
        if name is None:
            return

        metadata = {"agent_id": run_id, "agent_name": name, "span_role": "agent"}
        if error is not None:
            metadata["error_type"] = type(error).__name__
        self._step_manager.push_intermediate_step(
            IntermediateStepPayload(
                UUID=run_id,
                event_type=IntermediateStepType.WORKFLOW_END,
                name=name,
                metadata=TraceMetadata(provided_metadata=metadata),
            )
        )


class AIQLangchainProfilerHandler(LangchainProfilerHandler):
    """Preserve NAT's profiler behavior while naming DeepAgents task spans."""

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        serialized = dict(serialized)
        serialized["name"] = _task_display_name(serialized, input_str, inputs)
        return await super().on_tool_start(serialized, input_str, inputs=inputs, **kwargs)


@contextmanager
def aiq_langchain_profiler_context() -> Iterator[AIQLangchainProfilerHandler]:
    """Replace NAT's inherited profiler for one AIQ job without adding a duplicate callback."""
    from nat.plugins.profiler.decorators.framework_wrapper import callback_handler_var

    profiler = AIQLangchainProfilerHandler()
    token = callback_handler_var.set(profiler)
    try:
        yield profiler
    finally:
        callback_handler_var.reset(token)
