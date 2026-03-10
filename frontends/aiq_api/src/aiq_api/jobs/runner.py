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

"""
Agent-agnostic job runner.

Provides the Dask task function for running any registered agent with:
- NAT's JobStore for job metadata and status
- SSE event streaming for real-time UI updates
- Cancellation monitoring for graceful job termination
- Phoenix/OpenTelemetry observability via NAT's ExporterManager
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from typing import Any

from .callbacks import AgentEventCallback
from .event_store import BatchingEventStore
from .event_store import EventStore

logger = logging.getLogger(__name__)


def _normalize_trace_id(trace_id: int | str | None) -> int | None:
    """Convert trace ID to integer format.

    Args:
        trace_id: Trace ID as int, hex string, or None.

    Returns:
        Integer trace ID or None.
    """
    if trace_id is None:
        return None
    if isinstance(trace_id, int):
        return trace_id
    try:
        return int(trace_id, 16)
    except ValueError:
        return int(trace_id)


class CancellationMonitor:
    """
    Monitors job status for cancellation requests.

    Polls the job store at regular intervals and sets an asyncio.Event
    when the job status changes to INTERRUPTED.
    """

    def __init__(
        self,
        scheduler_address: str,
        db_url: str,
        job_id: str,
        poll_interval: float = 1.0,
    ):
        self.scheduler_address = scheduler_address
        self.db_url = db_url
        self.job_id = job_id
        self.poll_interval = poll_interval
        self._cancelled = asyncio.Event()
        self._monitor_task: asyncio.Task | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def _poll_job_status(self) -> None:
        """Poll job status and set cancelled event if interrupted."""
        from nat.front_ends.fastapi.job_store import JobStatus
        from nat.front_ends.fastapi.job_store import JobStore

        job_store = JobStore(scheduler_address=self.scheduler_address, db_url=self.db_url)

        while not self._cancelled.is_set():
            try:
                job = await job_store.get_job(self.job_id)
                if job and job.status == JobStatus.INTERRUPTED.value:
                    logger.info("Cancellation detected for job %s", self.job_id)
                    self._cancelled.set()
                    break
            except Exception as e:
                logger.warning("Error checking job status for %s: %s", self.job_id, e)

            await asyncio.sleep(self.poll_interval)

    def start(self) -> None:
        """Start the cancellation monitor background task."""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._poll_job_status())
            logger.debug("Started cancellation monitor for job %s", self.job_id)

    def stop(self) -> None:
        """Stop the cancellation monitor."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None
            logger.debug("Stopped cancellation monitor for job %s", self.job_id)

    def check(self) -> None:
        """Check if cancelled and raise CancelledError if so."""
        if self._cancelled.is_set():
            raise asyncio.CancelledError("Job cancelled by user")


# Interval for emitting heartbeat events
HEARTBEAT_INTERVAL_SECONDS = 30


async def run_with_cancellation(
    coro,
    monitor: CancellationMonitor,
    event_store: EventStore | BatchingEventStore | None = None,
) -> Any:
    """
    Run a coroutine with cancellation monitoring and periodic heartbeats.

    Emits job.heartbeat events every 30s so the SSE stream stays alive
    and the ghost job reaper can detect dead workers.
    Raises asyncio.CancelledError if the monitor detects cancellation.
    """
    import time

    task = asyncio.create_task(coro)
    monitor.start()
    start_time = time.monotonic()
    last_heartbeat = start_time

    try:
        while not task.done():
            if monitor.is_cancelled:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise asyncio.CancelledError("Job cancelled by user")

            now = time.monotonic()
            if event_store and (now - last_heartbeat) >= HEARTBEAT_INTERVAL_SECONDS:
                last_heartbeat = now
                event_store.store(
                    {
                        "type": "job.heartbeat",
                        "data": {"uptime_seconds": int(now - start_time)},
                    }
                )

            await asyncio.sleep(0.1)

        return task.result()
    finally:
        monitor.stop()


def _load_agent_class(agent_class_path: str) -> type:
    """
    Dynamically load an agent class from its module path.

    Args:
        agent_class_path: Full path like 'aiq_agent.agents.deep_researcher.agent.DeepResearcherAgent'

    Returns:
        The agent class.

    Raises:
        ImportError: If the module or class cannot be found.
    """
    module_path, class_name = agent_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def run_agent_job(
    configure_logging: bool,
    log_level: int,
    scheduler_address: str,
    db_url: str,
    config_file_path: str,
    job_id: str,
    input_text: str,
    agent_class_path: str,
    agent_config_name: str,
    parent_span_id: str | None = None,
    parent_function_id: str | None = None,
    parent_function_name: str | None = None,
    parent_workflow_run_id: str | None = None,
    parent_workflow_trace_id: int | str | None = None,
    parent_conversation_id: str | None = None,
    available_documents: list[dict] | None = None,
    data_sources: list[str] | None = None,
):
    """
    Dask task to run any registered agent with cancellation support and telemetry.

    This function is submitted to Dask and runs in a worker process. It:
    - Uses NAT's JobStore for status tracking
    - Monitors for cancellation requests and gracefully terminates the agent
    - Exports telemetry to Phoenix/OpenTelemetry via NAT's ExporterManager
    - Propagates trace context from parent workflow for nested spans

    Args:
        configure_logging: Whether to set up logging in the worker.
        log_level: Logging level to use.
        scheduler_address: Dask scheduler address.
        db_url: Database URL for job store and event store.
        config_file_path: Path to NAT config file.
        job_id: Unique job identifier.
        input_text: User input/query to run.
        agent_class_path: Full module path to agent class.
        agent_config_name: NAT config function name for the agent.
        parent_span_id: Parent span ID for trace continuity (from caller context).
        parent_function_id: Parent function ID for span hierarchy.
        parent_function_name: Parent function name for span metadata.
        parent_workflow_run_id: Parent workflow run ID for trace grouping.
        parent_workflow_trace_id: Parent trace ID (int or hex string) for trace continuity.
        parent_conversation_id: Conversation ID for session grouping in Phoenix.
        available_documents: Optional list of document dicts with file_name and summary.
    """

    from aiq_agent.common import LLMProvider
    from aiq_agent.common import LLMRole
    from aiq_agent.common import VerboseTraceCallback
    from aiq_agent.common import is_verbose
    from nat.builder.framework_enum import LLMFrameworkEnum
    from nat.builder.workflow_builder import WorkflowBuilder
    from nat.front_ends.fastapi.job_store import JobStatus
    from nat.front_ends.fastapi.job_store import JobStore
    from nat.runtime.loader import load_config

    if configure_logging:
        try:
            from nat.utils.log_utils import setup_logging

            setup_logging(log_level)
        except ImportError:
            import logging as std_logging

            std_logging.basicConfig(level=log_level)

    job_store: JobStore | None = None
    cancellation_monitor: CancellationMonitor | None = None
    event_store: EventStore | BatchingEventStore | None = None
    logger.info(
        "Dask worker received: agent=%s, config=%s, job_id=%s",
        agent_class_path,
        agent_config_name,
        job_id,
    )

    try:
        job_store = JobStore(scheduler_address=scheduler_address, db_url=db_url)
        await job_store.update_status(job_id, JobStatus.RUNNING)

        cancellation_monitor = CancellationMonitor(
            scheduler_address=scheduler_address,
            db_url=db_url,
            job_id=job_id,
            poll_interval=1.0,
        )

        config = load_config(config_file_path)

        # Dynamically load the agent class
        agent_cls = _load_agent_class(agent_class_path)

        async with WorkflowBuilder.from_config(config=config) as builder:
            fn_config = builder.get_function_config(agent_config_name)

            # Get LLMs for deep_researcher (orchestrator required)
            orchestrator_llm = await builder.get_llm(
                fn_config.orchestrator_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN
            )
            planner_llm = None
            researcher_llm = None
            if hasattr(fn_config, "planner_llm") and fn_config.planner_llm:
                planner_llm = await builder.get_llm(fn_config.planner_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
            if hasattr(fn_config, "researcher_llm") and fn_config.researcher_llm:
                researcher_llm = await builder.get_llm(
                    fn_config.researcher_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN
                )

            llm = orchestrator_llm

            tools = await builder.get_tools(tool_names=fn_config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
            if data_sources is not None:
                from aiq_agent.common import filter_tools_by_sources

                tools = filter_tools_by_sources(tools, data_sources)

            # Set up telemetry/observability for Phoenix and OpenTelemetry
            from nat.builder.context import Context
            from nat.builder.context import ContextState
            from nat.data_models.intermediate_step import IntermediateStepPayload
            from nat.data_models.intermediate_step import IntermediateStepType
            from nat.data_models.intermediate_step import StreamEventData
            from nat.data_models.intermediate_step import TraceMetadata
            from nat.data_models.invocation_node import InvocationNode
            from nat.observability.exporter_manager import ExporterManager
            from nat.profiler.callbacks.langchain_callback_handler import LangchainProfilerHandler
            from nat.utils.reactive.subject import Subject

            telemetry_exporters = {
                name: configured.instance for name, configured in builder._telemetry_exporters.items()
            }
            exporter_manager = ExporterManager.from_exporters(telemetry_exporters)

            # Initialize context state with trace propagation from parent
            context_state = ContextState.get()
            context_state.workflow_run_id.set(job_id)
            if parent_conversation_id:
                context_state.conversation_id.set(parent_conversation_id)

            workflow_trace_id = _normalize_trace_id(parent_workflow_trace_id) or uuid.uuid4().int
            context_state.workflow_trace_id.set(workflow_trace_id)

            # Event stream for exporters to subscribe to
            event_stream = Subject()
            context_state.event_stream.set(event_stream)

            # Initialize span stack (triggers default ["root"])
            _ = context_state.active_span_id_stack

            # Set up span hierarchy metadata
            workflow_span_name = f"async_job:{agent_config_name}"
            context_state.active_function.set(
                InvocationNode(
                    function_name=workflow_span_name,
                    function_id=job_id,
                    parent_id=parent_function_id,
                    parent_name=parent_function_name,
                )
            )

            context = Context(context_state)

            workflow_metadata = TraceMetadata(
                provided_metadata={
                    "workflow_run_id": job_id,
                    "workflow_trace_id": f"{workflow_trace_id:032x}",
                    "conversation_id": parent_conversation_id,
                    "agent": agent_class_path,
                    "parent_workflow_run_id": parent_workflow_run_id,
                    "parent_workflow_name": parent_function_name,
                }
            )

            # Run with telemetry - exporter must start before pushing events
            async with exporter_manager.start(context_state=context_state):
                # Link to parent span if provided (for nested trace continuity)
                parent_metadata: TraceMetadata | None = None
                if parent_span_id and parent_span_id != "root":
                    parent_metadata = TraceMetadata(
                        provided_metadata={
                            "workflow_run_id": parent_workflow_run_id,
                            "workflow_trace_id": f"{workflow_trace_id:032x}",
                            "conversation_id": parent_conversation_id,
                            "workflow_name": parent_function_name,
                        }
                    )
                    context.intermediate_step_manager.push_intermediate_step(
                        IntermediateStepPayload(
                            UUID=parent_span_id,
                            event_type=IntermediateStepType.SPAN_START,
                            name=parent_function_name or "parent_workflow",
                            metadata=parent_metadata,
                        )
                    )

                # Push WORKFLOW_START first so LLM/tool events become children
                context.intermediate_step_manager.push_intermediate_step(
                    IntermediateStepPayload(
                        UUID=job_id,
                        event_type=IntermediateStepType.WORKFLOW_START,
                        name=workflow_span_name,
                        metadata=workflow_metadata,
                        data=StreamEventData(input=input_text),
                    )
                )

                # Create profiler callback AFTER workflow starts (ensures correct parent)
                nat_profiler_callback = LangchainProfilerHandler()

                # Set up LLM provider
                provider = LLMProvider()
                provider.set_default(llm)
                if orchestrator_llm:
                    provider.configure(LLMRole.ORCHESTRATOR, orchestrator_llm)
                if planner_llm:
                    provider.configure(LLMRole.PLANNER, planner_llm)
                if researcher_llm:
                    provider.configure(LLMRole.RESEARCHER, researcher_llm)

                verbose = is_verbose(getattr(fn_config, "verbose", False))
                callbacks = [VerboseTraceCallback()] if verbose else []

                raw_event_store = EventStore(db_url, job_id)
                event_store = BatchingEventStore(raw_event_store)
                callbacks.append(AgentEventCallback(event_store))
                callbacks.append(nat_profiler_callback)

                # Instantiate agent with callbacks
                agent = _create_agent_instance(
                    agent_cls=agent_cls,
                    llm_provider=provider,
                    llm=llm,
                    tools=tools,
                    fn_config=fn_config,
                    verbose=verbose,
                    callbacks=callbacks,
                )

                # Run agent - LLM/tool events will be nested under workflow span
                result = await _run_agent(
                    agent=agent,
                    input_text=input_text,
                    monitor=cancellation_monitor,
                    available_documents=available_documents,
                    data_sources=data_sources,
                    event_store=event_store,
                )

                # Emit WORKFLOW_END event for Phoenix
                context.intermediate_step_manager.push_intermediate_step(
                    IntermediateStepPayload(
                        UUID=job_id,
                        event_type=IntermediateStepType.WORKFLOW_END,
                        name=workflow_span_name,
                        metadata=workflow_metadata,
                        data=StreamEventData(output=_extract_result(result)),
                    )
                )

                if parent_metadata:
                    context.intermediate_step_manager.push_intermediate_step(
                        IntermediateStepPayload(
                            UUID=parent_span_id,
                            event_type=IntermediateStepType.SPAN_END,
                            name=parent_function_name or "parent_workflow",
                            metadata=parent_metadata,
                        )
                    )

                # Signal event stream completion
                event_stream.on_complete()

                # Flush any buffered events before updating status
                if hasattr(event_store, "flush"):
                    event_store.flush()

                # Extract report and update status inside the context manager
                # so the UI sees completion before exporter flush and cleanup
                report = _extract_result(result)
                await job_store.update_status(job_id, JobStatus.SUCCESS, output={"report": report})
                logger.info("Job %s completed (report: %d chars)", job_id, len(report))

    except asyncio.CancelledError:
        logger.info("Job %s cancelled", job_id)
        if job_store:
            try:
                job = await job_store.get_job(job_id)
                if job and job.status != JobStatus.INTERRUPTED.value:
                    await job_store.update_status(job_id, JobStatus.INTERRUPTED, error="cancelled by user")
            except (ConnectionError, TimeoutError, RuntimeError):
                pass

        if event_store is None:
            event_store = BatchingEventStore(EventStore(db_url, job_id))

        event_store.store(
            {
                "type": "job.cancelled",
                "data": {"reason": "cancelled by user"},
            }
        )
        if hasattr(event_store, "flush"):
            event_store.flush()

    except Exception as e:
        logger.exception("Job %s failed: %s", job_id, type(e).__name__)
        if job_store:
            await job_store.update_status(job_id, JobStatus.FAILURE, error=str(e))

        if event_store is None:
            event_store = BatchingEventStore(EventStore(db_url, job_id))

        event_store.store(
            {
                "type": "job.error",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            }
        )
        if hasattr(event_store, "flush"):
            event_store.flush()

    finally:
        # Ensure terminal-path events are not left in the batch buffer.
        if event_store is not None and hasattr(event_store, "flush"):
            event_store.flush()
        if cancellation_monitor:
            cancellation_monitor.stop()


def _create_agent_instance(
    agent_cls: type,
    llm_provider,
    llm,
    tools: list,
    fn_config,
    verbose: bool,
    callbacks: list,
):
    """
    Create an agent instance, supporting different constructor patterns.

    Tries in order:
    1. llm_provider + tools pattern (DeepResearcherAgent style)
    2. llm + tools pattern (simpler agents)
    """
    # Try llm_provider pattern first (DeepResearcherAgent)
    try:
        return agent_cls(
            llm_provider=llm_provider,
            tools=tools,
            max_loops=getattr(fn_config, "max_loops", 3),
            verbose=verbose,
            callbacks=callbacks,
        )
    except TypeError:
        pass

    # Try simpler llm + tools pattern
    try:
        return agent_cls(
            llm=llm,
            tools=tools,
            callbacks=callbacks,
        )
    except TypeError:
        pass

    # Fallback: just callbacks
    return agent_cls(callbacks=callbacks)


async def _run_agent(
    agent,
    input_text: str,
    monitor: CancellationMonitor,
    available_documents: list[dict] | None = None,
    data_sources: list[str] | None = None,
    event_store: EventStore | None = None,
) -> Any:
    """
    Run the agent, supporting different run() signatures.

    Tries:
    1. run(input_text: str) -> str (simple protocol)
    2. run(state) where state has messages (LangGraph pattern)
    """
    from langchain_core.messages import HumanMessage

    # Check if agent has a simple run(input_text) method
    if hasattr(agent, "run"):
        import inspect

        sig = inspect.signature(agent.run)
        params = list(sig.parameters.keys())

        # If first param is 'input_text' or 'query', use simple pattern
        if params and params[0] in ("input_text", "query", "input"):
            return await run_with_cancellation(
                agent.run(input_text),
                monitor,
                event_store=event_store,
            )

        # Otherwise assume state-based pattern
        # Try to find the agent's state class
        state_cls = _get_agent_state_class(agent)
        if state_cls:
            # Build state with available_documents if the class supports it
            state_kwargs = {"messages": [HumanMessage(content=input_text)]}
            if data_sources is not None:
                state_kwargs["data_sources"] = data_sources
            if available_documents:
                # Convert dicts to AvailableDocument if the state class expects them
                try:
                    from aiq_agent.knowledge import AvailableDocument

                    state_kwargs["available_documents"] = [AvailableDocument(**doc) for doc in available_documents]
                    logger.debug(
                        "Dask worker passing %d available documents to agent state",
                        len(available_documents),
                    )
                except (ImportError, TypeError):
                    # AvailableDocument not available or state doesn't support it
                    pass
            state = state_cls(**state_kwargs)
        else:
            # Fallback: create a simple dict state
            state = {"messages": [HumanMessage(content=input_text)]}
            if data_sources is not None:
                state["data_sources"] = data_sources
            if available_documents:
                state["available_documents"] = available_documents

        return await run_with_cancellation(
            agent.run(state),
            monitor,
            event_store=event_store,
        )

    raise TypeError(f"Agent {type(agent).__name__} does not have a run method")


def _get_agent_state_class(agent) -> type | None:
    """Try to find the state class for an agent."""
    agent_module = type(agent).__module__
    agent_name = type(agent).__name__

    # Try common patterns for state class names
    # e.g., DeepResearcherAgent -> DeepResearchAgentState, DeepResearcherAgentState
    state_name_patterns = [
        "AgentState",
        f"{agent_name}State",
        f"{agent_name.replace('Agent', '')}AgentState",  # DeepResearcher -> DeepResearcherAgentState
        f"{agent_name.replace('erAgent', '')}AgentState",  # DeepResearcherAgent -> DeepResearchAgentState
        "State",
    ]

    # Try models submodule first
    try:
        models_module = importlib.import_module(agent_module.replace(".agent", ".models"))
        for state_name in state_name_patterns:
            if hasattr(models_module, state_name):
                return getattr(models_module, state_name)

        # Also scan for any class ending with "State" that has a messages field
        for name in dir(models_module):
            if name.endswith("State") and not name.startswith("_"):
                cls = getattr(models_module, name)
                if isinstance(cls, type) and hasattr(cls, "model_fields"):
                    if "messages" in cls.model_fields:
                        return cls
    except (ImportError, AttributeError):
        pass

    # Try same module
    try:
        module = importlib.import_module(agent_module)
        for state_name in state_name_patterns:
            if hasattr(module, state_name):
                return getattr(module, state_name)
    except ImportError:
        pass

    return None


def _extract_result(result: Any) -> str:
    """Extract string result from various result formats."""
    # Direct string
    if isinstance(result, str):
        return result

    # State with messages
    if hasattr(result, "messages") and result.messages:
        last_msg = result.messages[-1]
        if hasattr(last_msg, "content"):
            return str(last_msg.content)

    # Dict with messages
    if isinstance(result, dict):
        if "messages" in result and result["messages"]:
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):
                return str(last_msg.content)
        if "report" in result:
            return str(result["report"])
        if "output" in result:
            return str(result["output"])

    return str(result) if result else ""


# Backwards compatibility alias
async def run_deep_research(
    configure_logging: bool,
    log_level: int,
    scheduler_address: str,
    db_url: str,
    config_file_path: str,
    job_id: str,
    input_text: str,
):
    """
    Legacy function for running deep research jobs.

    Preserved for backwards compatibility. New code should use run_agent_job directly.
    """
    await run_agent_job(
        configure_logging=configure_logging,
        log_level=log_level,
        scheduler_address=scheduler_address,
        db_url=db_url,
        config_file_path=config_file_path,
        job_id=job_id,
        input_text=input_text,
        agent_class_path="aiq_agent.agents.deep_researcher.agent.DeepResearcherAgent",
        agent_config_name="deep_research_agent",
    )
