<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# MCP Tools and Authentication

Model Context Protocol (MCP) is an open protocol that standardizes how applications expose tools and
context to LLM applications. The AIQ Blueprint is built on the NVIDIA NeMo Agent toolkit (NAT), so AIQ
can use MCP servers as data sources through NAT function groups.

This guide assumes your AIQ deployment is pinned to NAT `1.6.0`, the latest stable NAT release line at
the time this guide was written. It covers the common MCP integration patterns for AIQ:

- Connect AIQ to an existing MCP server with no user authentication.
- Connect AIQ to a protected MCP server with service-account credentials.
- Use native NAT OAuth MCP support for per-user MCP authorization.
- Build a custom AIQ tool that forwards the current AIQ user token.
- Publish an AIQ or NAT workflow as an MCP server.

For the full NAT MCP reference, see:

- [NAT MCP client guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/mcp-client.html)
- [NAT MCP authentication guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/auth/mcp-auth/index.html)
- [NAT MCP service-account authentication guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/auth/mcp-auth/mcp-service-account-auth.html)
- [NAT MCP server guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/run-workflows/mcp-server.html)

## Choose an Integration Pattern

Use the simplest pattern that matches your security requirements:

| Scenario | Recommended pattern | When to use |
|---|---|---|
| Public or internal MCP server with no per-user auth | `mcp_client` function group | The MCP server is reachable from AIQ and does not require a user token. |
| MCP server uses backend credentials | `mcp_client` with server-side environment variables, or NAT `mcp_service_account` | All AIQ users should use the same service identity or app-level credentials. |
| MCP server trusts the AIQ user's token | AIQ token pass-through with a custom MCP auth provider, MCP proxy, or custom AIQ tool | AIQ owns sign-in and the MCP server or gateway accepts the same bearer token. |
| Downstream API needs the AIQ web/API user's token | Custom AIQ/NAT tool using `aiq_agent.auth.get_auth_token()` | You control the tool code and need to forward the token already accepted by AIQ auth middleware. |
| MCP server requires its own user OAuth consent | Native NAT `per_user_mcp_client` with `mcp_oauth2` plus AIQ UI/backend integration | The upstream MCP server owns OAuth consent. Do not present this as out-of-the-box AIQ UI support unless you also wire the consent flow into the deployed frontend. |
| Another app should call AIQ tools over MCP | `nat mcp serve` or `nat fastmcp server run` | AIQ or another NAT workflow should become the MCP server. |

## Prerequisites

Install NAT and the MCP package from the stable release line used by your AIQ deployment:

```bash
uv pip install "nvidia-nat[mcp]==1.6.0" nvidia-nat-mcp==1.6.0
```

If you are using a newer stable NAT release, keep `nvidia-nat`, `nvidia-nat-core`,
`nvidia-nat-eval`, and `nvidia-nat-mcp` on the same release line.

If your checkout still pins an older NAT release, update the NAT pins before using the native NAT
`mcp_service_account`, `mcp_oauth2`, or `per_user_mcp_client` examples below.

You can inspect the installed MCP component schemas with:

```bash
nat info components -t function_group -q mcp_client
nat info components -t auth_provider -q mcp_oauth2
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
- `sse`: backward-compatible transport. Avoid it for production auth scenarios.

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
The registry auto-detects function groups and maps every discovered tool back to the source using NAT
function-group prefixes, such as `mcp_financial_tools__get_stock_quote`.

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

Use `include`, `exclude`, and `tool_overrides` when the MCP server exposes more tools than AIQ should
use, or when the upstream descriptions are too generic for reliable tool routing.

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
backend identity, not an individual AIQ user's identity. This is the preferred pattern for CI, batch
jobs, shared enterprise data sources, and container deployments.

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

## Current AIQ UI Auth Support

The current AIQ UI supports one auth signal for data sources:

```yaml
requires_auth: true
```

When this flag is set, the UI disables the source until the user is signed in to AIQ. This is enough
for:

- AIQ token pass-through, where AIQ owns login and forwards the AIQ token.
- Custom AIQ tools that use `aiq_agent.auth.get_auth_token()`.
- Backend/service-account MCP tools that should only be visible to signed-in AIQ users.

It is not enough for native per-MCP OAuth consent by itself. The current data source API returns
`id`, `name`, `description`, and `requires_auth`; it does not return per-MCP auth status, a connect
URL, scopes, token expiry, or reconnect/disconnect actions.

If you want first-class native MCP OAuth in the AIQ UI, add a separate integration layer:

- Backend APIs to report each MCP source's auth status.
- Backend APIs to start and complete the MCP OAuth flow.
- UI controls for connect, reconnect, disconnect, error states, and expired consent.
- Async job validation to ensure the worker can resolve the user's MCP token.

Without that work, prefer AIQ token pass-through or service-account MCP for AIQ deployments.

## Per-User OAuth MCP Servers (Native NAT Capability)

Use native NAT OAuth MCP support when the protected MCP server implements MCP OAuth and each user must
authorize access to their own data. This is supported by NAT, but it should be treated as an advanced
AIQ integration path until the AIQ frontend and backend expose the per-MCP consent flow.

NAT provides:

- `mcp_oauth2`: an auth provider for MCP OAuth2 flows.
- `per_user_mcp_client`: a per-user MCP client function group.
- Secure token storage options for persisting and isolating per-user MCP tokens.

A typical NAT configuration looks like this:

```yaml
function_groups:
  jira_mcp:
    _type: per_user_mcp_client
    server:
      transport: streamable-http
      url: ${CORPORATE_MCP_JIRA_URL}
      auth_provider: jira_oauth

authentication:
  jira_oauth:
    _type: mcp_oauth2
    server_url: ${CORPORATE_MCP_JIRA_URL}
    redirect_uri: ${NAT_REDIRECT_URI:-http://localhost:8000/auth/redirect}
```

For production or remote development, set `NAT_REDIRECT_URI` to the public URL that the user's
browser can reach:

```bash
export NAT_REDIRECT_URI="https://aiq.example.com/auth/redirect"
```

Then register the MCP group as an authenticated data source so the AIQ UI disables it until a user is
signed in:

```yaml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: jira
        name: "Jira"
        description: "Search and inspect Jira issues through MCP."
        requires_auth: true
        tools:
          - jira_mcp
```

Native per-user MCP OAuth is the right pattern when the MCP server owns the OAuth flow. In AIQ, do
not rely on `requires_auth: true` alone for this pattern. Validate the consent flow end to end with
the frontend mode you deploy, especially if you use async jobs, because OAuth consent and token storage
are managed by NAT's MCP auth layer rather than AIQ's request-token helper.

## AIQ Token Pass-Through to MCP Servers

Use AIQ token pass-through when AIQ is the only login surface and the MCP server, an API gateway, or
an authenticating reverse proxy accepts the AIQ user's bearer token. In this pattern, users sign in to
AIQ once. AIQ forwards that request token when a tool call reaches the MCP server. For the AIQ login
and token retrieval setup, see [Authentication](../deployment/authentication.md).

This is different from native MCP OAuth:

- AIQ owns the user session and token validation at the AIQ boundary.
- The MCP server trusts the AIQ token, or a gateway exchanges or validates it before forwarding.
- Users do not complete a separate OAuth consent flow for each MCP server.
- `requires_auth: true` only gates the UI source toggle. It does not, by itself, make `mcp_client`
  forward an `Authorization` header to the MCP server.

There are three common ways to implement pass-through.

### Option 1: Custom MCP Auth Provider

If your deployment uses NAT's MCP client directly and you want the MCP server to remain a real MCP
server, add a small custom NAT authentication provider that reads the current AIQ token and injects it
into MCP client requests. The provider should call `aiq_agent.auth.get_auth_token()` at request time,
not at startup, so concurrent users and async jobs do not share credentials.

Configure the MCP client to use that provider:

```yaml
function_groups:
  internal_mcp:
    _type: mcp_client
    server:
      transport: streamable-http
      url: ${INTERNAL_MCP_URL}
      auth_provider: aiq_user_token

authentication:
  aiq_user_token:
    _type: aiq_user_token_passthrough
```

Register the group as an authenticated data source:

```yaml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: internal_mcp
        name: "Internal MCP"
        description: "Call internal MCP tools using your AIQ sign-in."
        requires_auth: true
        tools:
          - internal_mcp
```

This keeps the MCP boundary intact but requires a small code plugin because the token source is
AIQ-specific.

### Option 2: Auth-Forwarding MCP Proxy

Run a small internal proxy between AIQ and the MCP server. AIQ calls the proxy as its MCP server, and
the proxy forwards the AIQ bearer token to the upstream MCP server or exchanges it for an upstream
token. This is useful when:

- The upstream MCP server expects custom headers or token exchange.
- You want centralized policy, auditing, or allowlisting outside the AIQ process.
- Multiple AIQ deployments should share the same MCP access policy.

The AIQ YAML still uses `mcp_client`, but it must include whatever auth provider forwards the AIQ
token to the proxy:

```yaml
function_groups:
  internal_mcp:
    _type: mcp_client
    server:
      transport: streamable-http
      url: ${AIQ_MCP_PROXY_URL}
      auth_provider: aiq_user_token
```

The proxy receives the user's token from AIQ, then applies your organization's upstream policy. If the
proxy is implemented as an AIQ custom tool rather than an MCP server, use Option 3.

### Option 3: Custom AIQ Tool

If you do not need a real MCP client boundary inside AIQ, write a custom AIQ/NAT tool that retrieves
the AIQ token with `get_auth_token()` and calls the downstream service directly. This is usually the
simplest pass-through implementation when you control the downstream API. See
[Custom AIQ Auth-Based Tools](#custom-aiq-auth-based-tools) and
[Authentication](../deployment/authentication.md#step-5-use-the-current-user-token-in-tools).

## Does AIQ Need Separate UI Login for Each MCP Server?

It depends on which auth pattern you choose:

| Pattern | Separate MCP-server login in the AIQ UI? | Notes |
|---|---|---|
| Unauthenticated MCP | No | No user credential is needed. |
| Service-account MCP | No | AIQ uses backend credentials from config or secret storage. |
| AIQ token pass-through | No | Users sign in to AIQ once; the MCP server trusts or exchanges the AIQ token. |
| Native MCP OAuth with `mcp_oauth2` / `per_user_mcp_client` | Yes, for first-time consent per protected MCP server or OAuth resource | NAT manages MCP OAuth consent and token storage. The AIQ UI should expose or preserve that flow in the deployed frontend mode. |

For pass-through, the current AIQ UI behavior is usually enough: mark the source with
`requires_auth: true` so it is disabled until the user signs in to AIQ. For native MCP OAuth, plan for
additional UI/flow validation because the user may need to approve each MCP server's scopes and the UI
must not hide or break NAT's OAuth consent flow.

## Custom AIQ Auth-Based Tools

Use a custom AIQ/NAT tool when you want the tool to call a downstream service with the same bearer
token that authenticated the current AIQ request. This is not native MCP OAuth. It is a practical
AIQ-specific pattern for services that trust the AIQ user's JWT or for gateways that perform
on-behalf-of authorization.

AIQ exposes:

- `aiq_agent.auth.get_auth_token()`: returns the current request token when available.
- `aiq_agent.auth.get_current_principal()`: returns verified identity metadata from AIQ auth middleware.
- Async job token propagation: AIQ captures the request token and makes it available in Dask workers
  through the same `get_auth_token()` helper.

Example custom tool:

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

Register the tool as an auth-required data source:

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

This pattern is best when:

- AIQ already validates the user's JWT.
- The downstream service accepts that JWT or an exchange derived from it.
- You need AIQ UI toggles and async deep research jobs to preserve user context.

Do not use unverified JWT payloads for authorization decisions. Use `get_current_principal()` for
trusted identity and `get_auth_token()` only for forwarding a token to a trusted downstream service.

## Publish AIQ or NAT Tools as an MCP Server

You can publish the functions in a NAT workflow as MCP tools:

```bash
nat mcp serve --config_file configs/config_web_frag.yml --port 9901
```

The MCP server is available at:

```text
http://localhost:9901/mcp
```

List tools exposed by the server:

```bash
nat mcp client tool list --url http://localhost:9901/mcp
nat mcp client tool list --url http://localhost:9901/mcp --tool <tool_name> --detail
```

Call a tool directly while debugging:

```bash
nat mcp client tool call <tool_name> \
  --url http://localhost:9901/mcp \
  --json-args '{"query": "example"}'
```

NAT also supports a FastMCP server runtime:

```bash
uv pip install nvidia-nat-fastmcp
nat fastmcp server run --config_file configs/config_web_frag.yml --port 9902
```

FastMCP publishes tools at `http://localhost:9902/mcp` by default. NAT's FastMCP docs note that this
runtime depends on a beta FastMCP release, so validate it against your deployment requirements before
using it in production.

## Security Guidance

- Prefer `streamable-http` for MCP servers, especially protected servers.
- Do not expose `nat mcp serve` directly to the public internet without an authenticating reverse
  proxy, private network boundary, or equivalent protection.
- Do not use `sse` for production authentication scenarios.
- Store secrets in environment variables or a secret manager, not in YAML checked into source control.
- Use service-account MCP auth only when shared app-level access is acceptable.
- Use per-user OAuth MCP auth or a custom AIQ token-forwarding tool when access must reflect the
  signed-in user.
- Keep token forwarding scoped to trusted internal services and HTTPS endpoints.
- Mark user-authenticated data sources with `requires_auth: true` so the UI can prevent unauthenticated
  use.

## Troubleshooting

### MCP Tools Do Not Appear in the UI

Confirm the function group is listed in `data_source_registry`:

```yaml
tools:
  - mcp_financial_tools
```

The AIQ UI gets its connection list from `GET /v1/data_sources`. If a source is missing from the
registry, the UI has no toggle for it.

### The Agent Does Not Use the MCP Tool

Check the remote tool descriptions:

```bash
nat mcp client tool list --url http://localhost:9901/mcp --tool <tool_name> --detail
```

If descriptions are vague, add `tool_overrides` with task-specific descriptions. You may also need to
update prompts so agents know when to prefer the new source.

### Data Source Filtering Does Not Match MCP Tools

AIQ maps function groups by prefix. A group named `mcp_financial_tools` maps tools such as
`mcp_financial_tools__stock_price` back to the source containing `mcp_financial_tools`. If you use
individual tool references instead of the group name, list the exact exposed tool names.

### Authenticated Source Is Disabled in the UI

If a source has `requires_auth: true`, the UI disables it until the user has an auth token. Verify the
frontend auth provider is configured and that requests include an `idToken` cookie or
`Authorization: Bearer <token>` header.

### Async Deep Research Loses User Auth

Use `get_auth_token()` inside custom AIQ tools rather than reading request headers directly. AIQ
captures the request token during job submission and restores it in the async worker context.

### OAuth Redirect Fails on a Remote Server

Set `NAT_REDIRECT_URI` to the public URL users open in their browsers, not to `localhost`:

```bash
export NAT_REDIRECT_URI="https://aiq.example.com/auth/redirect"
```

Ensure the reverse proxy forwards `/auth/redirect` to the NAT server handling the OAuth callback.

## Related Documentation

- [Tools and Sources](./tools-and-sources.md)
- [Adding a Tool](../extending/adding-a-tool.md)
- [Adding a Data Source](../extending/adding-a-data-source.md)
- [Prompts](./prompts.md)
