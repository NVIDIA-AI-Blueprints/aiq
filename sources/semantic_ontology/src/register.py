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

"""Semantic Ontology chat query tool.

Queries the Semantic Ontology assistant's chat API (``POST /api/chat/completions``) and
returns its final answer. Semantic Ontology and AI-Q authenticate against the same NVIDIA SSO
provider, so this tool forwards the current user's SSO bearer token; Semantic Ontology
validates it against NVIDIA's JWKS before answering.

Semantic Ontology answers as a Server-Sent Events stream: ``step`` progress events, then a
single ``result`` event carrying the answer (and optionally generated SQL).
This tool consumes the stream and returns the final answer text to the agent.
"""

import asyncio
import json
import logging
import os
import time
import uuid

import httpx
from langchain_core.callbacks import adispatch_custom_event
from pydantic import Field
from pydantic import field_validator

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

# Name of the tool as exposed to the agent / rendered in the UI.
TOOL_NAME = "semantic_ontology_query"

# Custom LangChain event name used to stream Semantic Ontology's mid-run plan
# status (e.g. "extracting entities") to the AI-Q UI. The AgentEventCallback
# registers an ``on_custom_event`` handler that turns these into ``tool.update``
# SSE events. See ``aiq_api.jobs.callbacks.AgentEventCallback.on_custom_event``.
STATUS_EVENT_NAME = "semantic_ontology_status"

# Prefix tagging the NAT CUSTOM intermediate steps that carry plan statuses to
# the interactive-chat (WebSocket) UI. Plan statuses are emitted as CUSTOM
# events (not TOOL) so they are not miscounted as tool calls in traces /
# tokenomics. NAT's ``StepAdaptor`` is patched to let these tagged CUSTOM
# events through its filter and render them as a clean, indented status step
# titled by the label (the prefix is stripped).
CHAT_STATUS_STEP_PREFIX = "semantic_ontology_status::"


class SemanticOntologyQueryToolConfig(FunctionBaseConfig, name="semantic_ontology_query"):
    """Tool that asks the Semantic Ontology assistant a question and returns its answer.

    Semantic Ontology is reached over the same NVIDIA SSO trust domain as AI-Q: the current
    user's SSO token is forwarded as a Bearer token, which Semantic Ontology validates against
    NVIDIA's JWKS.
    """

    base_url: str = Field(
        default_factory=lambda: os.environ.get("SEMANTIC_ONTOLOGY_BASE_URL", ""),
        validate_default=True,
        description=(
            "Base URL of the Semantic Ontology frontend (HTTPS required). "
            "Defaults to the SEMANTIC_ONTOLOGY_BASE_URL environment variable."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def _require_https(cls, v: str) -> str:
        if v and v.startswith("http://"):
            raise ValueError("base_url must use HTTPS, not HTTP")
        return v

    path: str = Field(
        default="/api/chat/completions",
        description="Chat completions endpoint path on the Semantic Ontology frontend.",
    )
    timeout_seconds: float = Field(
        default=120.0,
        description="Overall request timeout. Semantic Ontology runs a text-to-SQL agent, so allow ample time.",
    )


def _push_chat_status(label: str) -> None:
    """Surface a plan-status label in the interactive chat (WebSocket) UI.

    The chat/WebSocket UI renders NAT intermediate steps via NAT's
    ``StepAdaptor``. The tool emits its plan statuses (e.g. "extracting
    entities") as CUSTOM intermediate steps — CUSTOM rather than TOOL so they
    are not miscounted as tool calls in traces / tokenomics — tagged with
    ``CHAT_STATUS_STEP_PREFIX``. Only the START is rendered; the END exists
    solely to keep NAT's span stack balanced.
    """
    from nat.builder.context import Context
    from nat.data_models.intermediate_step import IntermediateStepPayload
    from nat.data_models.intermediate_step import IntermediateStepType
    from nat.data_models.intermediate_step import StreamEventData

    manager = Context.get().intermediate_step_manager
    step_uuid = str(uuid.uuid4())
    tagged_name = f"{CHAT_STATUS_STEP_PREFIX}{label}"
    manager.push_intermediate_step(
        IntermediateStepPayload(
            UUID=step_uuid,
            event_type=IntermediateStepType.CUSTOM_START,
            name=tagged_name,
            data=StreamEventData(input=label),
        )
    )
    manager.push_intermediate_step(
        IntermediateStepPayload(
            UUID=step_uuid,
            event_type=IntermediateStepType.CUSTOM_END,
            name=tagged_name,
            data=StreamEventData(output="done"),
        )
    )


async def _emit_status(label: str | None) -> None:
    """Stream a Semantic Ontology plan-status label to the AI-Q UI.

    Semantic Ontology's text-to-SQL agent streams ``step`` events (e.g.
    "extracting entities") as its plan progresses. AI-Q has two independent UI
    streaming paths, so we feed both, best-effort:

    - **Deep-research (async jobs) SSE** — a LangChain custom event that
      ``AgentEventCallback.on_custom_event`` turns into a ``tool.update`` SSE
      event, shown under the running tool. Requires an active agent run with
      the SSE event callback in context (absent in CLI/tests → skipped).
    - **Interactive chat (WebSocket)** — a NAT intermediate step (see
      ``_push_chat_status``), rendered as a thinking step.
    """
    if not label:
        return
    try:
        await adispatch_custom_event(
            STATUS_EVENT_NAME,
            {"tool": TOOL_NAME, "label": label},
        )
    except Exception as exc:  # no parent run / no callbacks in context
        logger.debug("semantic_ontology_query: could not emit SSE status %r: %s", label, exc)
    try:
        _push_chat_status(label)
    except Exception as exc:  # no active NAT context (e.g. CLI/tests)
        logger.debug("semantic_ontology_query: could not emit chat status %r: %s", label, exc)


@register_function(config_type=SemanticOntologyQueryToolConfig)
async def semantic_ontology_query(tool_config: SemanticOntologyQueryToolConfig, builder: Builder):
    timeout = httpx.Timeout(tool_config.timeout_seconds, connect=10.0)

    async def _semantic_ontology_query(question: str) -> str:
        """Ask the Semantic Ontology assistant a question about internal structured data.

        Semantic Ontology answers questions over NVIDIA-internal structured datasets (it
        generates and runs SQL, then explains the result). Prefer this tool for
        questions about internal metrics, records, or tabular/database-backed
        data that Semantic Ontology owns.

        Args:
            question (str): A natural-language question for the Semantic Ontology assistant.

        Returns:
            str: The Semantic Ontology assistant's final answer, including any generated SQL.
        """
        from aiq_agent.auth import get_auth_token

        if not tool_config.base_url:
            return (
                "Error: Semantic Ontology base URL is not configured. "
                "Set the SEMANTIC_ONTOLOGY_BASE_URL environment variable."
            )
        endpoint = f"{tool_config.base_url.rstrip('/')}{tool_config.path}"

        token = get_auth_token()
        if not token:
            logger.warning("semantic_ontology_query: no auth token available; cannot call Semantic Ontology")
            return (
                "Error: Semantic Ontology query is unavailable because no authentication token is available. "
                "Please sign in so your SSO token can be forwarded to Semantic Ontology."
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            # Identify AI-Q as the caller so Semantic Ontology can attribute/segment the request.
            "x-gsf-source": "AIQ",
        }
        payload = {"question": question}

        answer_text: str | None = None
        sql_code: str | None = None
        sql_result: object | None = None
        error_message: str | None = None

        # Semantic Ontology serves one conversation at a time and returns 409 while busy. The
        # research agents may fire several semantic_ontology_query calls close together, so
        # retry on 409 with backoff to serialize against that single slot.
        # The overall deadline caps all attempts + backoff sleeps within timeout_seconds.
        max_409_retries = 6
        overall_deadline = time.monotonic() + tool_config.timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                for attempt in range(max_409_retries + 1):
                    if time.monotonic() >= overall_deadline:
                        return "Error: Semantic Ontology request timed out."
                    async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                        logger.debug(
                            "semantic_ontology_query: HTTP %s from %s (attempt %s)",
                            response.status_code,
                            endpoint,
                            attempt + 1,
                        )
                        if response.status_code == 409 and attempt < max_409_retries:
                            await response.aclose()
                            sleep_secs = min(2.0 * (attempt + 1), max(0.0, overall_deadline - time.monotonic()))
                            await asyncio.sleep(sleep_secs)
                            continue
                        if response.status_code == 401:
                            body = await response.aread()
                            logger.warning(
                                "semantic_ontology_query: 401 — server=%s www-authenticate=%s",
                                response.headers.get("server"),
                                response.headers.get("www-authenticate"),
                            )
                            logger.debug("semantic_ontology_query: 401 body=%r", body.decode(errors="replace")[:300])
                            return (
                                "Error: Semantic Ontology rejected the request (401 Unauthorized). Your SSO token may "
                                "have expired or Semantic Ontology does not trust this token's issuer."
                            )
                        if response.status_code == 409:
                            return "Error: Semantic Ontology is busy with another conversation. Please retry shortly."
                        if response.status_code >= 400:
                            body = (await response.aread()).decode(errors="replace")[:500]
                            logger.warning(
                                "semantic_ontology_query: HTTP %s error body=%r",
                                response.status_code,
                                body,
                            )
                            return (
                                f"Error: Semantic Ontology returned an unexpected error (HTTP {response.status_code})."
                            )

                        async for line in response.aiter_lines():
                            # SSE: payload lines start with "data: "; comment
                            # lines (heartbeats like ": ping") and blanks are
                            # ignored.
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:") :].strip()
                            if not data or data == "[DONE]":
                                if data == "[DONE]":
                                    break
                                continue
                            try:
                                event = json.loads(data)
                            except json.JSONDecodeError:
                                logger.debug("Skipping non-JSON SSE payload from Semantic Ontology: %r", data[:200])
                                continue

                            event_type = event.get("type")
                            if event_type == "result":
                                answer = event.get("answer") or {}
                                answer_text = answer.get("response")
                                sql_code = answer.get("sql_code")
                                sql_result = answer.get("sql_response_from_db")
                            elif event_type == "step":
                                # Semantic Ontology streams "step" events as its
                                # text-to-SQL plan progresses (e.g. "extracting
                                # entities"). Surface each label to the AI-Q UI as
                                # a live status under the running tool.
                                label = event.get("label")
                                logger.debug(
                                    "semantic_ontology_query: received plan step %r (node=%s)", label, event.get("node")
                                )
                                await _emit_status(label)
                            elif event_type == "error":
                                error_message = event.get("message") or "Unknown error from Semantic Ontology."

                    # Got a non-409 response and consumed its stream; stop retrying.
                    break
        except httpx.TimeoutException:
            return "Error: Semantic Ontology request timed out."
        except httpx.HTTPError as e:
            logger.error("Semantic Ontology query request failed: %s", e)
            return f"Error: Could not reach Semantic Ontology — {e}"

        if error_message:
            return f"Error: Semantic Ontology reported — {error_message}"
        if not answer_text:
            return "Semantic Ontology returned no answer."

        parts = [answer_text]
        if sql_code:
            parts.append(f"<sql>\n{sql_code}\n</sql>")
        if sql_result is not None:
            # Include the actual query result rows so the agent can state concrete
            # values (e.g. a count of 0) instead of treating an empty/zero result
            # as "no data found".
            parts.append(f"<sql_result>\n{json.dumps(sql_result)}\n</sql_result>")
        return "\n\n".join(parts)

    yield FunctionInfo.from_fn(
        _semantic_ontology_query,
        description=_semantic_ontology_query.__doc__,
    )
