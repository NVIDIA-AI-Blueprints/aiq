<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# MCP Tools

Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context to LLMs. You can use MCP to connect the AIQ Blueprint to external tools and data sources served by remote MCP servers, without writing any custom Python code. Since the AIQ Blueprint is built on the NVIDIA NeMo Agent toolkit, MCP integration is available through configuration.

For the full MCP documentation, refer to the [NeMo Agent Toolkit MCP Client Guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/).

## Prerequisites

Install MCP support if it is not already available:

```bash
uv pip install "nvidia-nat[mcp]"
```

## Adding an MCP Tool

Use `mcp_tool_wrapper` to connect to an MCP server and wrap a single tool as a function. This is the simplest way to add an external tool to the deep researcher.

### Step 1: Define the MCP tool in the `functions` section

```yaml
functions:
  # ... existing tools (web_search_tool, paper_search_tool, and so on) ...

  mcp_financial_data:
    _type: mcp_tool_wrapper
    url: "http://localhost:9901/mcp"           # URL of the MCP server
    transport: "streamable-http"                # recommended transport
    mcp_tool_name: "get_financial_data"         # name of the tool on the MCP server
    description: "Retrieves financial data and market information. Use this tool when the research query involves financial analysis, stock data, or market trends."
```

**Transport options:**

- `streamable-http` (recommended): modern HTTP-based transport for new deployments
- `sse`: Server-Sent Events, supported for backwards compatibility
- `stdio`: standard input/output for local process communication (use `mcp_client` instead of `mcp_tool_wrapper` for this transport)

### Step 2: Add the tool to each agent's `tools` list

The agents will not use the tool unless it appears in their `tools` list. Add it to the agents that should have access:

```yaml
functions:
  intent_classifier:
    _type: intent_classifier
    tools:
      - web_search_tool
      - paper_search_tool
      - knowledge_search
      - mcp_financial_data

  shallow_research_agent:
    _type: shallow_research_agent
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_data

  deep_research_agent:
    _type: deep_research_agent
    tools:
      - paper_search_tool
      - advanced_web_search_tool
      - knowledge_search
      - mcp_financial_data
```

## Wrapping Multiple Tools

If the MCP server exposes multiple tools, define one `mcp_tool_wrapper` entry per tool:

```yaml
functions:
  mcp_stock_quote:
    _type: mcp_tool_wrapper
    url: "http://localhost:9901/mcp"
    transport: "streamable-http"
    mcp_tool_name: "get_stock_quote"
    description: "Returns the current stock price for a given ticker symbol."
  mcp_earnings_report:
    _type: mcp_tool_wrapper
    url: "http://localhost:9901/mcp"
    transport: "streamable-http"
    mcp_tool_name: "get_earnings_report"
    description: "Returns the latest earnings report for a given company."
```

## Dynamic Tool Discovery with `mcp_client`

Instead of wrapping tools one by one, `mcp_client` can automatically discover and register all tools from an MCP server. This is placed under `function_groups` rather than `functions`:

```yaml
function_groups:
  financial_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: "http://localhost:9901/mcp"
```

All tools served by that MCP server become available using the function group name (`financial_tools`) in the agents' `tools` lists.

A complete example config is available at `configs/config_web_frag_mcp.yml`.

## Authenticated MCP Tools

MCP tools that require OAuth2 authentication (for example, corporate Jira, Confluence, or internal data platforms) are not supported in the current version of the AIQ Blueprint. The NeMo Agent toolkit provides an `mcp_oauth2` authentication provider, but it is not yet compatible with the blueprint's backend and frontend. Support for authenticated MCP tools is planned for an upcoming release.

For non-authenticated MCP servers, or MCP servers that use service account credentials (set through environment variables on the server side), use the `mcp_tool_wrapper` approach described above.

## UI Limitations

MCP tools added through the configuration file will be available to the agents at the backend level, but they will not automatically appear in the demo UI. Displaying custom MCP tools in the UI requires changes to both the backend and frontend. Built-in support for this is planned for an upcoming version. In the meantime, the demo UI source code is provided and can be modified to surface additional tools as needed.

## Prompt Tuning

Adding an MCP tool to the config makes it available to the agents, but the agents' prompts may not reference it. For the agents to use MCP tools effectively, you should tune the relevant prompts so that the agent knows when and how to invoke the new tool. Each customization is different: the prompt changes depend on the tool's purpose and how it fits into the research workflow.

For example, if you add a financial data MCP tool, ensure the tool's `description` field clearly explains what it does and when to use it. The NeMo Agent toolkit agents use tool descriptions for routing decisions. A good description such as *"Retrieves real-time stock prices and financial statements. Use this tool for any questions involving company financials, stock performance, or market data."* helps the agent select it for the right queries.

For more on prompt customization, refer to [Prompts](./prompts.md).

## Discovering MCP Tools

You can list the tools served by any MCP server:

```bash
nat info mcp --url http://localhost:9901/mcp
```

To get details about a specific tool:

```bash
nat info mcp --url http://localhost:9901/mcp --tool get_financial_data
```
