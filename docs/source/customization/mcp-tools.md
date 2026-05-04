<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# MCP Tools and Authentication

Model Context Protocol (MCP) is an open protocol that standardizes how applications expose tools and
context to LLM applications. The AIQ Blueprint is built on the NVIDIA NeMo Agent toolkit (NAT), so
AIQ can use MCP servers as data sources through NAT function groups.

This guide is written for AIQ 2.1 deployments running NAT `1.6.0` or later. Verify your installed
version with `uv pip show nvidia-nat`.

## What this guide covers

**Supported in AIQ 2.1:**

- Connect AIQ to an unauthenticated MCP server.
- Connect AIQ to an MCP server with backend service-account credentials.
- Forward the signed-in AIQ user's identity to a downstream service from a custom AIQ tool.
- Publish AIQ workflows as an MCP server.

**Planned for AIQ 2.2 / 2.3:**

- Native per-user MCP OAuth driven by the AIQ UI. NAT 1.6 ships the protocol-level support
  (`mcp_oauth2`, `per_user_mcp_client`); the AIQ UI cannot yet drive per-MCP consent. See the
  short [planning note](#per-user-mcp-oauth-planned) below.
- A first-party AIQ-token pass-through MCP auth provider. Today, if your MCP server trusts the AIQ
  user's bearer token, you must implement and register a custom NAT auth provider in your
  deployment package.

For the full NAT MCP reference:

- [NAT MCP client guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/mcp-client.html)
- [NAT MCP service-account auth guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/auth/mcp-auth/mcp-service-account-auth.html)
- [NAT MCP server guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/run-workflows/mcp-server.html)

## Choose an Integration Pattern

| Scenario | Pattern | Section |
|---|---|---|
| MCP server has no per-user auth | `mcp_client` function group | [Connect AIQ to an MCP Server](#connect-aiq-to-an-mcp-server) |
| MCP server uses backend / app credentials | `mcp_client` + `mcp_service_account` | [Service-Account MCP Servers](#service-account-mcp-servers) |
| Downstream API trusts the AIQ user's bearer token | Custom AIQ tool using `get_auth_token()` | [Forwarding AIQ User Identity](#forwarding-aiq-user-identity-from-a-tool) |
| MCP server requires per-user OAuth consent | Planned for AIQ 2.2 / 2.3 | [Per-User MCP OAuth (planned)](#per-user-mcp-oauth-planned) |
| Another app should call AIQ tools over MCP | `nat mcp serve` or `nat fastmcp server run` | [Publish AIQ as an MCP Server](#publish-aiq-tools-as-an-mcp-server) |

## Prerequisites

Install NAT and the MCP package on the same release line as your AIQ deployment:

```bash
uv pip install "nvidia-nat[mcp]==1.6.0" nvidia-nat-mcp==1.6.0
```

Keep `nvidia-nat`, `nvidia-nat-core`, `nvidia-nat-eval`, and `nvidia-nat-mcp` on the same release
line. If you are pinning newer NAT minor releases, bump all four together.

You can inspect the installed MCP component schemas with:

```bash
nat info components -t function_group -q mcp_client
nat info components -t auth_provider -q mcp_service_account
```

## Connect AIQ to an MCP Server

Use `mcp_client` to connect to an MCP server and make its tools available to AIQ agents. The
`mcp_client` function group discovers remote tools and registers them as NAT functions.

```yaml
function_groups:
  mcp_financial_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: ${MCP_SERVER_URL:-http://localhost:9901/mcp}
```

Supported transports:

- `streamable-http`: recommended for new deployments and required for protected MCP servers.
- `stdio`: useful for local MCP servers started as subprocesses.
- `sse`: backward-compatible. Avoid it for production auth scenarios.

### Register the MCP Group as a Data Source

Add the function group to `data_source_registry`. The registry is AIQ's source of truth for UI
toggles, per-message data source filtering, and default tool inheritance.

```yaml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: web_search
        name: "Web Search"
        description: "Search the web for real-time information."
        tools:
          - web_search_tool
          - advanced_web_search_tool
      - id: financial_data
        name: "Financial Data"
        description: "Query financial reports and market data through MCP."
        tools:
          - mcp_financial_tools
```

When an AIQ agent has no explicit `tools` list, it inherits all tools from `data_source_registry`.
The registry auto-detects function groups and maps every discovered tool back to the source using
NAT function-group prefixes, such as `mcp_financial_tools__get_stock_quote`.

Use `exclude_tools` to specialize individual agents:

```yaml
functions:
  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_nano_llm
    exclude_tools:
      - mcp_financial_tools__expensive_long_running_tool
```

### Limit and Rename MCP Tools

Use `include`, `exclude`, and `tool_overrides` when the MCP server exposes more tools than AIQ
should use, or when the upstream descriptions are too generic for reliable tool routing.

```yaml
function_groups:
  mcp_financial_tools:
    _type: mcp_client
    include:
      - get_stock_quote
      - get_earnings_report
    server:
      transport: streamable-http
      url: ${MCP_SERVER_URL:-http://localhost:9901/mcp}
    tool_overrides:
      get_stock_quote:
        alias: stock_price
        description: "Returns the current stock price for a ticker symbol."
      get_earnings_report:
        description: "Returns the latest quarterly earnings report for a company."
```

## Service-Account MCP Servers

Use service-account authentication when the MCP server should be accessed with an application or
backend identity, not an individual AIQ user's identity. This is the preferred pattern for CI,
batch jobs, shared enterprise data sources, and container deployments.

```yaml
function_groups:
  mcp_enterprise_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: ${ENTERPRISE_MCP_URL}
      auth_provider: enterprise_service_account

authentication:
  enterprise_service_account:
    _type: mcp_service_account
    client_id: ${SERVICE_ACCOUNT_CLIENT_ID}
    client_secret: ${SERVICE_ACCOUNT_CLIENT_SECRET}
    token_url: ${SERVICE_ACCOUNT_TOKEN_URL}
    scopes:
      - enterprise.read
```

For MCP servers that require both an OAuth2 service-account token and a service-specific delegation
token, add a `service_token` block:

```yaml
authentication:
  enterprise_dual_auth:
    _type: mcp_service_account
    client_id: ${SERVICE_ACCOUNT_CLIENT_ID}
    client_secret: ${SERVICE_ACCOUNT_CLIENT_SECRET}
    token_url: ${SERVICE_ACCOUNT_TOKEN_URL}
    scopes:
      - enterprise.read
    service_token:
      token: ${ENTERPRISE_SERVICE_TOKEN}
      header: X-Service-Account-Token
```

Register the function group in `data_source_registry` the same way as unauthenticated MCP tools. If
the source does not require the end user to sign in to AIQ, leave `requires_auth` unset or `false`.

```yaml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: enterprise_mcp
        name: "Enterprise MCP"
        description: "Search enterprise systems using service-account credentials."
        tools:
          - mcp_enterprise_tools
```

## Forwarding AIQ User Identity from a Tool

When a downstream API or MCP gateway already trusts the AIQ user's bearer token, the supported
AIQ 2.1 pattern is a small custom AIQ tool that reads the request token with
`aiq_agent.auth.get_auth_token()` and forwards it on the outbound call. This works whether the
downstream service is a real MCP server, an HTTP API, or a gateway in front of one.

AIQ exposes:

- `aiq_agent.auth.get_auth_token()` — returns the current request token when available.
- `aiq_agent.auth.get_current_principal()` — returns verified identity metadata from AIQ auth
  middleware (use this for authorization decisions; do not trust unverified JWT payloads).
- Async job token propagation — AIQ captures the request token at submit time and makes it
  available in Dask workers through the same `get_auth_token()` helper. The token is **not**
  refreshed inside the worker, so jobs that outlive the access token's TTL will fail mid-execution
  on auth-required tool calls; in-worker refresh is on the AIQ 2.2 roadmap.

Example custom tool that forwards the AIQ user's token to an internal search service:

```python
from pydantic import Field

from aiq_agent.auth import get_auth_token
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig


class InternalSearchConfig(FunctionBaseConfig, name="internal_search"):
    endpoint: str = Field(..., description="Internal search endpoint")


@register_function(config_type=InternalSearchConfig)
async def internal_search(config: InternalSearchConfig, builder):
    async def _search(query: str) -> str:
        token = get_auth_token()
        if not token:
            return "Sign in before using Internal Search."

        # Use an async HTTP client in production code.
        # Forward only to trusted services over HTTPS.
        # `call_internal_search` is a placeholder for your own async HTTP call, e.g.:
        #   async with httpx.AsyncClient() as client:
        #       resp = await client.get(config.endpoint, params={"q": query},
        #                               headers={"Authorization": f"Bearer {token}"})
        #       return resp.text
        return await call_internal_search(
            endpoint=config.endpoint,
            query=query,
            headers={"Authorization": f"Bearer {token}"},
        )

    yield FunctionInfo.from_fn(
        _search,
        description="Search internal systems using the signed-in AIQ user's token.",
    )
```

Register the tool as an auth-required data source so the UI disables it until the user signs in:

```yaml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: internal_search
        name: "Internal Search"
        description: "Search internal systems using your AIQ sign-in."
        requires_auth: true
        tools:
          - internal_search

  internal_search:
    _type: internal_search
    endpoint: ${INTERNAL_SEARCH_URL}
```

This is the AIQ-user-identity MCP pattern fully supported in 2.1. The two alternatives —
protocol-level pass-through via a custom NAT auth provider, and an auth-forwarding MCP proxy — are
viable in NAT but are not first-class in AIQ 2.1; treat them as deployment-side extensions.

For the broader auth context (UI sign-in flow, validator registration, headless API callers), see
[Authentication](../deployment/authentication.md).

## Per-User MCP OAuth (planned)

NAT 1.6 ships the protocol-level building blocks for per-user MCP OAuth — `mcp_oauth2` (auth
provider for MCP OAuth flows) and `per_user_mcp_client` (function group with per-user token
storage). What AIQ 2.1 **does not yet** ship is the UI integration that drives this flow: the
data-source API does not return per-MCP auth status, connect / disconnect URLs, scopes, or token
expiry, and the UI has no per-source "Connect" / "Reconnect" controls.

Until that lands, the recommended patterns for AIQ deployments remain:

- **Service-account MCP** when the access can be shared at the application level.
- **AIQ user-identity tools** (the section above) when the downstream service trusts the AIQ
  bearer token.

Beyond the UI, two further gaps exist in 2.1: AIQ's `/v1/data_sources` does not surface per-MCP
auth status (connect URL, scopes, token expiry, error state), and async deep research jobs cannot
yet resolve per-user MCP tokens inside Dask workers. The full per-user MCP OAuth integration —
backend status APIs, UI controls, and worker-side token resolution — is tracked on the AIQ 2.2 /
2.3 roadmap. Refer to the
[NAT MCP authentication guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/auth/mcp-auth/index.html)
if you want to follow NAT's MCP OAuth surface directly.

## Publish AIQ Tools as an MCP Server

You can publish the functions in a NAT workflow as MCP tools:

```bash
nat mcp serve --config_file configs/config_web_frag.yml --port 9901
```

The MCP server is available at `http://localhost:9901/mcp`.

List tools and call them while debugging:

```bash
nat mcp client tool list --url http://localhost:9901/mcp
nat mcp client tool list --url http://localhost:9901/mcp --tool <tool_name> --detail

nat mcp client tool call <tool_name> \
  --url http://localhost:9901/mcp \
  --json-args '{"query": "example"}'
```

NAT also supports a FastMCP server runtime:

```bash
uv pip install nvidia-nat-fastmcp
nat fastmcp server run --config_file configs/config_web_frag.yml --port 9902
```

FastMCP publishes tools at `http://localhost:9902/mcp` by default. NAT's FastMCP docs note this
runtime depends on a beta FastMCP release; validate against your deployment requirements before
using it in production.

## Security Guidance

- Prefer `streamable-http` for MCP servers, especially protected servers. Avoid `sse` for
  production authentication scenarios.
- Do not expose `nat mcp serve` to the public internet without an authenticating reverse proxy or
  private network boundary.
- Store secrets in environment variables or a secret manager, not in YAML checked into source
  control.
- Use service-account MCP auth only when shared app-level access is acceptable.
- Keep token forwarding scoped to trusted internal services and HTTPS endpoints.
- Mark user-authenticated data sources with `requires_auth: true` so the UI can prevent
  unauthenticated use.

## Troubleshooting

### MCP Tools Do Not Appear in the UI

Confirm the function group is listed in `data_source_registry`. The AIQ UI gets its connection
list from `GET /v1/data_sources`; if a source is missing from the registry, the UI has no toggle
for it.

### The Agent Does Not Use the MCP Tool

Check the remote tool descriptions:

```bash
nat mcp client tool list --url http://localhost:9901/mcp --tool <tool_name> --detail
```

If descriptions are vague, add `tool_overrides` with task-specific descriptions. You may also need
to update prompts so agents know when to prefer the new source.

### Data Source Filtering Does Not Match MCP Tools

AIQ maps function groups by prefix. A group named `mcp_financial_tools` maps tools such as
`mcp_financial_tools__stock_price` back to the source containing `mcp_financial_tools`. If you
list individual tool references instead of the group name, list the exact exposed tool names.

### Authenticated Source Is Disabled in the UI

If a source has `requires_auth: true`, the UI disables it until the user has an auth token. Verify
the frontend auth provider is configured and that requests include an `idToken` cookie or
`Authorization: Bearer <token>` header.

### Async Deep Research Loses User Auth Mid-Job

Use `get_auth_token()` inside custom AIQ tools rather than reading request headers directly — AIQ
captures the request token at job submit and restores it in the async worker context (see
[Authentication → Use the current user token in tools](../deployment/authentication.md#step-5-use-the-current-user-token-in-tools)).
Note that the access token is **not** refreshed inside the worker, so jobs that outlive the
token's TTL will fail mid-execution; in-worker refresh is on the AIQ 2.2 roadmap.

## Related Documentation

- [Authentication](../deployment/authentication.md)
- [Tools and Sources](./tools-and-sources.md)
- [Adding a Tool](../extending/adding-a-tool.md)
- [Adding a Data Source](../extending/adding-a-data-source.md)
- [Prompts](./prompts.md)
