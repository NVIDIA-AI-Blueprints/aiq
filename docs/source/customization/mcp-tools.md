<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# MCP Tools

Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context to LLMs. You can use MCP to connect the AIQ Blueprint to external tools and data sources served by remote MCP servers, without writing any custom Python code. Since the AIQ Blueprint is built on the NVIDIA NeMo Agent toolkit, MCP integration is available through configuration using `mcp_client`.

For the full MCP documentation, refer to the [NeMo Agent Toolkit MCP Client Guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/workflows/mcp/mcp-client.html).

## Prerequisites

Install MCP support if it is not already available:

```bash
uv pip install nvidia-nat-mcp==1.4.0
```

## Starting an Example MCP Server

Before connecting as a client, you need an MCP server to connect to. You can publish any NeMo Agent toolkit workflow as an MCP server using `nat mcp serve`.

For example, given a workflow config at `my_workflow.yml`:

```bash
nat mcp serve --config_file my_workflow.yml --port 9901
```

This starts an MCP server on `http://localhost:9901/mcp` using `streamable-http` transport. All functions defined in the workflow become available as MCP tools.

You can list the tools served by any MCP server:

```bash
nat mcp client tool list --url http://localhost:9901/mcp
```

To get details about a specific tool:

```bash
nat mcp client tool list --url http://localhost:9901/mcp --tool <tool_name> --detail
```

For more details on deploying MCP servers, refer to the [NeMo Agent Toolkit MCP Server Guide](https://docs.nvidia.com/nemo/agent-toolkit/latest/workflows/mcp/mcp-server.html).

## Adding MCP Tools to the Deep Researcher

Use `mcp_client` to connect to an MCP server and make its tools available to the deep researcher. The `mcp_client` automatically discovers all tools served by the MCP server and registers them as functions.

### Step 1: Define the MCP client in the `function_groups` section

Add a `function_groups` section to your config (at the same level as `functions`):

```yaml
function_groups:
  mcp_financial_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: "http://localhost:9901/mcp"
```

This connects to the MCP server at the given URL and registers all of its tools under the group name `mcp_financial_tools`.

**Transport options:**

- `streamable-http` (recommended): modern HTTP-based transport for new deployments
- `sse`: Server-Sent Events, supported for backwards compatibility
- `stdio`: standard input/output for local process communication

### Step 2: Add the function group to each agent's `tools` list

The agents will not use the MCP tools unless the function group appears in their `tools` list. Add it to the agents that should have access:

```yaml
# (inside the existing functions: section)
  intent_classifier:
    _type: intent_classifier
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_tools

  clarifier_agent:
    _type: clarifier_agent
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_tools

  shallow_research_agent:
    _type: shallow_research_agent
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_tools

  deep_research_agent:
    _type: deep_research_agent
    tools:
      - advanced_web_search_tool
      - knowledge_search
      - mcp_financial_tools
```

### Complete Example Config

Below is a complete config that adds MCP tools to the deep researcher alongside the existing web search and knowledge search tools. This extends `config_web_frag.yml`:

```yaml
general:
  use_uvloop: true
  telemetry:
    logging:
      console:
        _type: console
        level: INFO

  front_end:
    _type: aiq_api
    runner_class: aiq_api.plugin.AIQAPIWorker
    db_url: ${NAT_JOB_STORE_DB_URL:-sqlite+aiosqlite:///./jobs.db}
    expiry_seconds: 86400
    cors:
      allow_origin_regex: 'http://localhost(:\d+)?|http://127.0.0.1(:\d+)?'
      allow_methods:
        - GET
        - POST
        - DELETE
        - OPTIONS
      allow_headers:
        - "*"
      allow_credentials: true
      expose_headers:
        - "*"

llms:
  nemotron_llm_intent:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.5
    top_p: 0.9
    max_tokens: 4096
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

  nemotron_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.1
    top_p: 0.3
    max_tokens: 16384
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

  gpt_oss_llm:
    _type: nim
    model_name: openai/gpt-oss-120b
    base_url: https://integrate.api.nvidia.com/v1
    temperature: 1.0
    top_p: 1.0
    max_tokens: 256000
    api_key: ${NVIDIA_API_KEY}
    max_retries: 10

  nemotron_llm_deep:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 1.0
    top_p: 1.0
    max_tokens: 128000
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

# MCP Tools: connect to an external MCP server
function_groups:
  mcp_financial_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: ${MCP_SERVER_URL:-http://localhost:9901/mcp}

functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true

  knowledge_search:
    _type: knowledge_retrieval
    backend: foundational_rag
    collection_name: ${COLLECTION_NAME:-test_collection}
    top_k: 5
    rag_url: ${RAG_SERVER_URL:-http://localhost:8081}
    ingest_url: ${RAG_INGEST_URL:-http://localhost:8082}
    timeout: 300

  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_tools

  clarifier_agent:
    _type: clarifier_agent
    llm: gpt_oss_llm
    planner_llm: nemotron_llm
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_tools
    max_turns: 3
    enable_plan_approval: true
    log_response_max_chars: 2000
    verbose: true

  shallow_research_agent:
    _type: shallow_research_agent
    llm: gpt_oss_llm
    tools:
      - web_search_tool
      - knowledge_search
      - mcp_financial_tools
    max_llm_turns: 10
    max_tool_iterations: 5

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: gpt_oss_llm
    researcher_llm: nemotron_llm_deep
    planner_llm: gpt_oss_llm
    max_loops: 2
    tools:
      - advanced_web_search_tool
      - knowledge_search
      - mcp_financial_tools

workflow:
  _type: chat_deepresearcher_agent
  enable_escalation: true
  enable_clarifier: true
  use_async_deep_research: true
  checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}
```

## Overriding Tool Names and Descriptions

By default, `mcp_client` exposes all tools from the MCP server. You can rename or override descriptions for specific tools using `tool_overrides`:

```yaml
function_groups:
  mcp_financial_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: "http://localhost:9901/mcp"
    tool_overrides:
      get_stock_quote:
        alias: "stock_price"
        description: "Returns the current stock price for a given ticker symbol."
      get_earnings_report:
        description: "Returns the latest quarterly earnings report for a company."
```

## Authenticated MCP Tools

MCP tools that require OAuth2 authentication (for example, corporate Jira, Confluence, or internal data platforms) are not supported in the current version of the AIQ Blueprint. The NeMo Agent toolkit provides an `mcp_oauth2` authentication provider, but it is not yet compatible with the blueprint's backend and frontend. Support for authenticated MCP tools is planned for an upcoming release.

For non-authenticated MCP servers, or MCP servers that use service account credentials (set through environment variables on the server side), use the `mcp_client` approach described above.

## UI Limitations

MCP tools added through the configuration file will be available to the agents at the backend level, but they will not automatically appear in the demo UI. Displaying custom MCP tools in the UI requires changes to both the backend and frontend. Built-in support for this is planned for an upcoming version. In the meantime, the demo UI source code is provided and can be modified to surface additional tools as needed.

## Prompt Tuning

Adding MCP tools to the config makes them available to the agents, but the agents' prompts may not reference them. For the agents to use MCP tools effectively, you should tune the relevant prompts so that the agent knows when and how to invoke the new tools. Each customization is different: the prompt changes depend on the tool's purpose and how it fits into the research workflow.

The NeMo Agent toolkit agents use tool descriptions for routing decisions. If the MCP server provides poor or generic tool descriptions, you can override them through the `tool_overrides` configuration to help the agent select the right tool for each query.

For more on prompt customization, refer to [Prompts](./prompts.md).
