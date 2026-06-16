# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Linchpin check: can a worker-style context resolve a connected per-user MCP
source's tools using the token already stored in Redis?

This mirrors what jobs/runner.py would do per job: set Context.user_id, then build
the per_user_mcp_client group — which connects to MaaS, authenticates with the
stored token (no interactive flow), and enumerates the user's Drive tools.

Requires: Redis up, a *valid* (unexpired) token in Redis for USER (re-connect via
scripts/run_mcp_auth_demo.py first if expired).

    uv run python scripts/check_mcp_tool_resolution.py
"""

from __future__ import annotations

import asyncio
import os

from nat.runtime.loader import PluginTypes
from nat.runtime.loader import discover_and_register_plugins

discover_and_register_plugins(PluginTypes.ALL)

from nat.builder.context import ContextState  # noqa: E402
from nat.builder.workflow_builder import WorkflowBuilder  # noqa: E402
from nat.plugins.mcp.auth.auth_provider_config import MCPOAuth2ProviderConfig  # noqa: E402
from nat.plugins.mcp.client.client_config import MCPServerConfig  # noqa: E402
from nat.plugins.mcp.client.client_config import PerUserMCPClientConfig  # noqa: E402
from nat.plugins.mcp.client.client_impl import per_user_mcp_client_function_group  # noqa: E402
from nat.plugins.redis.object_store import RedisObjectStoreClientConfig  # noqa: E402

USER = os.environ.get("MCP_TEST_USER", "user:apanduwawala")
MAAS = os.environ.get("MCP_GDRIVE_URL", "https://maas.prd.astra.nvidia.com/maas/gdrive/mcp")


async def main() -> None:
    async with WorkflowBuilder() as b:
        await b.add_object_store(
            "mcp_token_store",
            RedisObjectStoreClientConfig(host="localhost", port=6379, bucket_name="mcp-tokens"),
        )
        await b.add_auth_provider(
            "mcp_oauth2_gdrive",
            MCPOAuth2ProviderConfig(
                server_url=MAAS,
                redirect_uri="http://localhost:8000/v1/auth/mcp/gdrive/callback",
                token_storage_object_store="mcp_token_store",
            ),
        )

        # This is the crux: the worker sets the job owner's id before building the
        # per-user group, so the MCP client authenticates as that user via the
        # stored token instead of an interactive flow.
        ContextState.get().user_id.set(USER)

        cfg = PerUserMCPClientConfig(
            server=MCPServerConfig(transport="streamable-http", url=MAAS, auth_provider="mcp_oauth2_gdrive"),
        )

        print(f"Building per-user MCP group for user={USER} against {MAAS} ...")
        async with per_user_mcp_client_function_group(cfg, b) as group:
            fns = await group.get_accessible_functions()
            print("\n=== RESOLVED DRIVE TOOLS ===")
            for name, fn in fns.items():
                desc = (getattr(fn, "description", "") or "").split("\n")[0][:80]
                print(f"  - {name}: {desc}")
            print(f"\nTotal: {len(fns)} tool(s).")

            # Prove the LangChain wrapping path the agent needs (mirrors NAT's
            # workflow_builder.get_tools group branch).
            from nat.builder.framework_enum import LLMFrameworkEnum

            wrapper = b._registry.get_tool_wrapper(llm_framework=LLMFrameworkEnum.LANGCHAIN)
            lc_tools = [wrapper.build_fn(n, fn, b) for n, fn in fns.items()]
            print("\n=== LANGCHAIN-WRAPPED ===")
            for t in lc_tools:
                print(f"  - {type(t).__name__}: name={getattr(t, 'name', '?')}")
            print(f"\n{len(lc_tools)} LangChain tool(s) ready to hand to the agent.")


if __name__ == "__main__":
    asyncio.run(main())
