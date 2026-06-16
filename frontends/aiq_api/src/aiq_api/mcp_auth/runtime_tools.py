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

"""Per-job runtime resolution of per-user MCP source tools (built in code).

AIQ agents inherit data-source tools at *build* time, but a per-user MCP source's
tools are per-user/dynamic — the MCP client connects and enumerates tools using
the *user's* token. Two consequences shaped this design:

  * The tools can't be inherited statically by agents (no user at build time).
  * A ``per_user_mcp_client`` declared in the *config* is built by NAT's per-user
    *interactive* (WebSocket) session builder, which fails for a user with no
    token — breaking interactive chat. So we do NOT declare it in config.

Instead the headless async-job worker builds the per-user MCP client **in code**,
per job, after it has set ``Context.user_id`` to the job owner: it reads the MCP
endpoint from the source's ``mcp_oauth2`` auth provider, connects with the owner's
stored token (no interactive flow), enumerates the tools, and wraps them for the
agent. The client stays open via the caller's ``AsyncExitStack`` for the run.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from aiq_agent.common.data_source_registry import get_all_sources
from nat.builder.framework_enum import LLMFrameworkEnum

logger = logging.getLogger(__name__)


async def open_per_user_mcp_tools(
    *,
    builder,
    data_sources: list[str] | None,
    exit_stack: AsyncExitStack,
    wrapper_type: LLMFrameworkEnum | str = LLMFrameworkEnum.LANGCHAIN,
) -> list:
    """Build per-user MCP clients for selected protected sources; return their tools.

    Args:
        builder: The per-job ``WorkflowBuilder`` (resolves the auth provider + the
            framework tool wrapper).
        data_sources: Selected source ids, or ``None`` meaning "all" (so every
            connected protected source's tools are made available).
        exit_stack: An ``AsyncExitStack`` whose lifetime spans the agent run; the
            MCP client contexts are entered here and torn down when it closes.
        wrapper_type: Agent framework to wrap tools for.

    Returns:
        Framework-wrapped tools (possibly empty). Best-effort: a failure resolving
        one source is logged and skipped, so it never breaks the job.

    Precondition: ``Context.user_id`` must already be set to the job owner.
    """
    from nat.plugins.mcp.client.client_config import MCPServerConfig
    from nat.plugins.mcp.client.client_config import MCPToolOverrideConfig
    from nat.plugins.mcp.client.client_config import PerUserMCPClientConfig
    from nat.plugins.mcp.client.client_impl import per_user_mcp_client_function_group

    selected = None if data_sources is None else {s.lower() for s in data_sources}
    tools: list = []

    for source in get_all_sources():
        pua = source.per_user_auth
        if pua is None or not pua.required or not pua.auth_provider:
            continue
        if selected is not None and source.id.lower() not in selected:
            continue

        try:
            # The mcp_oauth2 provider's server_url is the MCP endpoint; reuse it so
            # the connect flow and the job-time client target the same server, and
            # the client authenticates via the same provider (stored token lookup).
            provider = await builder.get_auth_provider(pua.auth_provider)
            server_url = str(getattr(getattr(provider, "config", None), "server_url", "") or "")
            if not server_url:
                logger.warning(
                    "Source '%s': auth provider '%s' has no server_url; cannot build MCP client.",
                    source.id,
                    pua.auth_provider,
                )
                continue

            # Give terse/blank MCP tools clear names + descriptions so the agent
            # reliably selects them over web search (declared on the source).
            tool_overrides = {
                name: MCPToolOverrideConfig(alias=ov.get("alias"), description=ov.get("description"))
                for name, ov in (pua.tool_overrides or {}).items()
            }
            client_cfg = PerUserMCPClientConfig(
                server=MCPServerConfig(transport="streamable-http", url=server_url, auth_provider=pua.auth_provider),
                tool_overrides=tool_overrides,
            )
            group = await exit_stack.enter_async_context(per_user_mcp_client_function_group(client_cfg, builder))
            fns = await group.get_accessible_functions()
            wrapper = builder._registry.get_tool_wrapper(llm_framework=wrapper_type)
            wrapped = [wrapper.build_fn(name, fn, builder) for name, fn in fns.items()]
            tools.extend(wrapped)

            # Map these runtime-resolved tools to their data source so the agents'
            # citation/source capture treats their results as sources. Without this,
            # get_source_id_for_tool returns None for them and shallow research raises
            # EmptySourceRegistryError ("no sources captured") even on a successful read.
            from aiq_agent.common.data_source_registry import register_tool_sources

            register_tool_sources({getattr(t, "name", ""): source.id for t in wrapped if getattr(t, "name", "")})
            logger.info("Resolved %d per-user MCP tool(s) for source '%s'.", len(wrapped), source.id)
        except Exception:
            logger.exception(
                "Failed to resolve per-user MCP tools for source '%s'; continuing without them.",
                source.id,
            )

    return tools
