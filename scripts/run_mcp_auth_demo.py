# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal runnable harness for the per-user MCP auth flow against NVIDIA MaaS.

Stands up ONLY the MCP-auth control plane (status / connect / callback) backed by
the real ``NatMcpAuthProvider`` + a real MaaS ``mcp_oauth2`` provider + real Redis
token storage. It deliberately skips the LLM/Dask/workflow stack so you can
exercise connect -> SSO -> callback -> token-in-Redis without an NVIDIA_API_KEY.

Run (needs the NVIDIA network + Redis on :6379):

    AIQ_PUBLIC_URL=http://localhost:8000 uv run python scripts/run_mcp_auth_demo.py

Then:
    curl -s -XPOST localhost:8000/v1/auth/mcp/gdrive/connect | jq    # -> auth_url
    # open auth_url in a browser, complete NVIDIA SSO
    curl -s localhost:8000/v1/auth/mcp/gdrive/status | jq            # -> "connected"
"""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI

from aiq_agent.auth import Principal
from aiq_agent.common.data_source_registry import populate_from_config
from aiq_agent.common.data_source_registry import reset_registry
from aiq_api.mcp_auth.factory import build_mcp_auth_provider
from aiq_api.routes import auth as auth_routes
from nat.builder.workflow_builder import WorkflowBuilder
from nat.plugins.mcp.auth.auth_provider_config import MCPOAuth2ProviderConfig
from nat.plugins.redis.object_store import RedisObjectStoreClientConfig
from nat.runtime.loader import PluginTypes
from nat.runtime.loader import discover_and_register_plugins

logging.basicConfig(level=logging.INFO)

# Register entry-point plugins (mcp_oauth2 auth provider, redis object store, ...)
# the way `WorkflowBuilder.from_config` does — a bare builder doesn't auto-load them.
discover_and_register_plugins(PluginTypes.ALL)

MAAS_URL = os.environ.get("MCP_GDRIVE_URL", "https://maas.prd.astra.nvidia.com/maas/gdrive/mcp")
PUBLIC_URL = os.environ.get("AIQ_PUBLIC_URL", "http://localhost:8000")
DEMO_USER = os.environ.get("USER", "demo")


async def main() -> None:
    reset_registry()
    populate_from_config(
        [
            {
                "id": "gdrive",
                "name": "Google Drive",
                "description": "Search and read your authorized Google Drive files.",
                "requires_auth": True,
                "per_user_auth": {
                    "required": True,
                    "provider": "google",
                    "mcp_server_id": "gdrive",
                    "auth_provider": "mcp_oauth2_gdrive",
                },
                "tools": ["mcp_gdrive"],
            },
        ]
    )

    async with WorkflowBuilder() as builder:
        await builder.add_object_store(
            "mcp_token_store",
            RedisObjectStoreClientConfig(
                host=os.environ.get("REDIS_HOST", "localhost"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                bucket_name="mcp-tokens",
            ),
        )
        await builder.add_auth_provider(
            "mcp_oauth2_gdrive",
            MCPOAuth2ProviderConfig(
                server_url=MAAS_URL,
                redirect_uri=f"{PUBLIC_URL}/v1/auth/mcp/gdrive/callback",
                token_storage_object_store="mcp_token_store",
            ),
        )

        provider = await build_mcp_auth_provider(builder)
        if not provider.is_protected("gdrive"):
            raise SystemExit("gdrive was not configured — check MaaS reachability / Redis.")
        # Generous challenge window for manual SSO during the demo (default is 5 min).
        from datetime import timedelta

        provider.challenge_ttl = timedelta(minutes=15)

        # The real API process authenticates the caller; here we stub a fixed
        # principal so the demo needs no auth middleware. Same principal is used
        # for connect and status so the token key matches.
        auth_routes.require_verified_principal = lambda: Principal(type="user", sub=DEMO_USER)

        app = FastAPI(title="MCP Auth Demo")
        auth_routes.register_mcp_auth_routes(app, provider)

        logging.info("MaaS MCP auth demo on %s  (user=%s)", PUBLIC_URL, DEMO_USER)
        logging.info("  POST %s/v1/auth/mcp/gdrive/connect", PUBLIC_URL)
        logging.info("  GET  %s/v1/auth/mcp/gdrive/status", PUBLIC_URL)
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info"))
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
