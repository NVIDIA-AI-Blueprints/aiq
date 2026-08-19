# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NeMo Relay framework integration helpers."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from typing import TypeVar
from uuid import uuid4

import nemo_relay
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware import ModelRequest
from langchain.agents.middleware import ModelResponse
from langchain.agents.middleware import ToolCallRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import messages_to_dict
from langchain_core.runnables import RunnableBinding
from langchain_core.runnables.config import merge_configs
from nemo_relay.integrations.langchain import NemoRelayMiddleware
from pydantic import BaseModel

_T = TypeVar("_T")
_aiq_scope_active: ContextVar[bool] = ContextVar("aiq_relay_scope_active", default=False)
logger = logging.getLogger(__name__)


@dataclass
class _AgentScopeLifecycle:
    handle: Any
    output: Any = None


def _log_capture_failure(operation: str, error: Exception) -> None:
    """Report Relay capture failures without exposing payloads or changing execution."""
    logger.warning("NeMo Relay: %s failed (error_type=%s)", operation, type(error).__name__)


@dataclass
class _NamedModelAdapter:
    """Give otherwise valid chat-model implementations a Relay call name."""

    wrapped: Any
    model_name: str

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped, name)


def _normalize_chat_nvidia_binding(
    runnable: Any,
    config: dict[str, Any],
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Expose a bound ChatNVIDIA model to Relay without losing bound tools.

    Relay 0.7.3 handles propagation headers through ``ChatNVIDIA.default_headers``
    only when the model is a direct ChatNVIDIA instance. LangChain's
    ``bind_tools()`` returns a RunnableBinding, which otherwise makes Relay fall
    back to the unsupported ``extra_headers`` model parameter.
    """
    try:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
    except ImportError:
        return runnable, {}, config

    if (
        not isinstance(runnable, RunnableBinding)
        or not isinstance(runnable.bound, ChatNVIDIA)
        or runnable.config_factories
    ):
        return runnable, {}, config

    return runnable.bound, dict(runnable.kwargs), merge_configs(runnable.config, config)


# Work around NVIDIA/NeMo-Relay#805 until DeepAgents emits nested local-subagent Agent scopes.
class _DelegatedAgentScopeMiddleware(AgentMiddleware):
    """Create a semantic Agent scope for the subagent selected by DeepAgents."""

    @staticmethod
    def _agent_name(request: Any) -> str | None:
        tool_call = getattr(request, "tool_call", None)
        if not isinstance(tool_call, dict) or tool_call.get("name") != "task":
            return None
        arguments = tool_call.get("args")
        if not isinstance(arguments, dict):
            return None
        name = arguments.get("subagent_type")
        return name if isinstance(name, str) and name else None

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        name = self._agent_name(request)
        if name is None:
            return handler(request)
        with agent_scope(name, input_value=getattr(request, "tool_call", None)) as lifecycle:
            result = handler(request)
            lifecycle.output = result
            return result

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        name = self._agent_name(request)
        if name is None:
            return await handler(request)
        with agent_scope(name, input_value=getattr(request, "tool_call", None)) as lifecycle:
            result = await handler(request)
            lifecycle.output = result
            return result


def deepagents_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Attach Relay's supported DeepAgents middleware."""

    from nemo_relay.integrations.deepagents import add_nemo_relay_integration

    observed = add_nemo_relay_integration(kwargs)
    middleware = list(observed.get("middleware") or ())
    if not any(isinstance(item, _DelegatedAgentScopeMiddleware) for item in middleware):
        middleware.append(_DelegatedAgentScopeMiddleware())
    observed["middleware"] = middleware
    return observed


def merge_langchain_middleware(middleware: Sequence[Any] | None) -> list[Any]:
    """Attach Relay managed execution to an application-owned LangChain agent."""
    merged = list(middleware or ())
    if not any(isinstance(item, NemoRelayMiddleware) for item in merged):
        merged.insert(0, NemoRelayMiddleware())
    return merged


async def ainvoke_with_relay(
    runnable: Any,
    input_value: Any,
    *,
    callbacks: Sequence[Any] | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Run a direct LangChain model call through Relay's maintained middleware."""
    effective_config = dict(config or {})
    configured_callbacks = callbacks if callbacks is not None else effective_config.get("callbacks")
    if configured_callbacks:
        effective_config["callbacks"] = list(configured_callbacks)
    else:
        effective_config.pop("callbacks", None)
    messages = list(input_value)
    system_message = (
        messages.pop(0) if messages and isinstance(messages[0], BaseMessage) and messages[0].type == "system" else None
    )
    model, model_settings, effective_config = _normalize_chat_nvidia_binding(runnable, effective_config)
    if not any(
        isinstance(getattr(model, attribute, None), str) and getattr(model, attribute)
        for attribute in ("model", "model_name", "model_id", "deployment_name")
    ):
        model = _NamedModelAdapter(model, type(model).__name__)
    request = ModelRequest(
        model=model,
        messages=messages,
        system_message=system_message,
        model_settings=model_settings,
    )

    async def invoke(next_request: ModelRequest[Any]) -> ModelResponse[Any]:
        next_messages = list(next_request.messages)
        if next_request.system_message is not None:
            next_messages.insert(0, next_request.system_message)
        parameters = inspect.signature(next_request.model.ainvoke).parameters
        accepts_config = "config" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        kwargs = dict(next_request.model_settings)
        if isinstance(next_request.model, _NamedModelAdapter) and not isinstance(
            next_request.model.wrapped,
            BaseChatModel,
        ):
            kwargs = {}
        if not any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            kwargs = {name: value for name, value in kwargs.items() if name in parameters}
        if accepts_config:
            response = await next_request.model.ainvoke(next_messages, config=effective_config, **kwargs)
        else:
            response = await next_request.model.ainvoke(next_messages, **kwargs)
        if not isinstance(response, BaseMessage):
            content = getattr(response, "content", None)
            if not isinstance(content, str | list):
                message = f"Relay-managed LangChain model returned {type(response).__name__}, expected BaseMessage"
                raise TypeError(message)
            response = AIMessage(content=content)
        return ModelResponse(result=[response])

    response = await NemoRelayMiddleware().awrap_model_call(request, invoke)
    if not response.result:
        raise RuntimeError("Relay-managed LangChain model returned no messages")
    return response.result[-1]


async def ainvoke_tool_with_relay(tool: Any, args: dict[str, Any]) -> Any:
    """Run a direct LangChain tool call through Relay's maintained middleware."""
    request = ToolCallRequest(
        tool_call={"name": tool.name, "args": args, "id": f"aiq-{uuid4()}"},
        tool=tool,
        state={},
        runtime=None,
    )

    async def invoke(next_request: ToolCallRequest) -> Any:
        if next_request.tool is None:
            raise RuntimeError(f"Relay-managed tool {next_request.tool_call['name']!r} is unavailable")
        return await next_request.tool.ainvoke(next_request.tool_call.get("args") or {})

    return await NemoRelayMiddleware().awrap_tool_call(request, invoke)


@contextmanager
def _semantic_scope(
    name: str,
    scope_type: Any,
    component_type: str,
    *,
    session_id: str | None = None,
    input_value: Any = None,
    metadata: dict[str, Any] | None = None,
):
    """Create a semantic scope and mark nested AI-Q scope execution."""
    scope_token = None
    if not _aiq_scope_active.get():
        scope_token = _aiq_scope_active.set(True)
    scope_metadata = {
        "aiq.component.name": name,
        "aiq.component.type": component_type,
        "aiq.framework": "nemo-agent-toolkit",
    }
    scope_metadata.update(metadata or {})
    if session_id:
        scope_metadata["session_id"] = session_id
    lifecycle = _AgentScopeLifecycle(None)
    status_metadata: dict[str, Any] = {"otel.status_code": "UNSET"}
    try:
        try:
            lifecycle.handle = nemo_relay.scope.push(
                name,
                scope_type,
                metadata=_safe_value(scope_metadata),
                input=_safe_value(input_value) if input_value is not None else None,
            )
        except Exception as capture_error:
            _log_capture_failure("semantic scope start", capture_error)
        try:
            yield lifecycle
        except BaseException as error:
            status_metadata = {
                "error_type": type(error).__name__,
                "otel.status_code": "ERROR",
                "otel.status_description": str(error),
            }
            raise
        else:
            status_metadata = {"otel.status_code": "OK"}
    finally:
        try:
            if lifecycle.handle is not None:
                try:
                    output = _safe_value(lifecycle.output) if lifecycle.output is not None else None
                    nemo_relay.scope.pop(lifecycle.handle, output=output, metadata=status_metadata)
                except Exception as capture_error:
                    _log_capture_failure("semantic scope end", capture_error)
        finally:
            if scope_token is not None:
                _aiq_scope_active.reset(scope_token)


@contextmanager
def agent_scope(name: str, *, session_id: str | None = None, input_value: Any = None):
    """Create an Agent scope around an application-owned agent boundary."""
    with _semantic_scope(
        name,
        nemo_relay.ScopeType.Agent,
        "agent",
        session_id=session_id,
        input_value=input_value,
    ) as lifecycle:
        yield lifecycle


@contextmanager
def workflow_scope(
    name: str,
    *,
    session_id: str | None = None,
    input_value: Any = None,
    metadata: dict[str, Any] | None = None,
):
    """Create a NAT workflow scope above application-owned agent scopes."""
    with _semantic_scope(
        name,
        nemo_relay.ScopeType.Function,
        "workflow",
        session_id=session_id,
        input_value=input_value,
        metadata=metadata,
    ) as lifecycle:
        yield lifecycle


async def run_agent(
    name: str,
    operation: Callable[[], Awaitable[_T]],
    *,
    session_id: str | None = None,
    input_value: Any = None,
) -> _T:
    """Run an agent with a fresh stack at a request boundary and shared stack when nested."""

    async def _run() -> _T:
        with agent_scope(name, session_id=session_id, input_value=input_value) as lifecycle:
            result = await operation()
            lifecycle.output = result
            return result

    if _aiq_scope_active.get():
        return await _run()

    async def _run_isolated() -> _T:
        with nemo_relay.use_scope_stack(nemo_relay.create_scope_stack()):
            return await _run()

    return await asyncio.create_task(_run_isolated())


async def run_workflow(
    name: str,
    operation: Callable[[], Awaitable[_T]],
    *,
    session_id: str | None = None,
    input_value: Any = None,
    metadata: dict[str, Any] | None = None,
) -> _T:
    """Run one NAT request as a Relay workflow root with semantic input and output."""

    async def _run() -> _T:
        with workflow_scope(
            name,
            session_id=session_id,
            input_value=input_value,
            metadata=metadata,
        ) as lifecycle:
            result = await operation()
            lifecycle.output = result
            return result

    if _aiq_scope_active.get():
        return await _run()

    async def _run_isolated() -> _T:
        with nemo_relay.use_scope_stack(nemo_relay.create_scope_stack()):
            return await _run()

    return await asyncio.create_task(_run_isolated())


def _safe_value(value: Any) -> Any:
    """Project framework state to JSON-compatible Relay event values."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_safe_value(item) for item in value]
    if isinstance(value, BaseMessage):
        return messages_to_dict([value])[0]
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return {"type": type(value).__name__}
