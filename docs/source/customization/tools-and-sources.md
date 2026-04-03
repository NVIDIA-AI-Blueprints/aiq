<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Tools and Sources

## Data Source Registry

The `data_source_registry` function is the **single source of truth** for which tools exist and which data source they belong to. It controls the UI toggles, per-message filtering, and -- by default -- which tools each agent receives.

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
      - id: knowledge_layer
        name: "Knowledge Base"
        description: "Search uploaded documents and files."
        tools:
          - knowledge_search
```

The `GET /v1/data_sources` API endpoint returns these entries, which the UI renders as toggles. When a user sends a message with `data_sources: ["web_search"]`, only tools belonging to that source are active for that request.

Tools not listed in any data source entry (e.g., utility tools like "think") are always included regardless of filtering.

## Auto-Inherit: Agents Get All Registry Tools by Default

When an agent's `tools` list is **empty** (the default), it automatically inherits every tool registered in `data_source_registry`. This means adding a new tool or data source requires only **one config change** -- adding it to the registry.

```yaml
functions:
  # Add a tool to the registry -- all agents get it automatically
  data_sources:
    _type: data_source_registry
    sources:
      - id: web_search
        name: "Web Search"
        tools:
          - web_search_tool
          - advanced_web_search_tool
      - id: knowledge_layer
        name: "Knowledge Base"
        tools:
          - knowledge_search

  # Agents with no tools list inherit all registry tools
  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent

  clarifier_agent:
    _type: clarifier_agent
    llm: nemotron_llm

  # Use exclude_tools for per-agent specialization
  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_llm
    exclude_tools:
      - advanced_web_search_tool    # shallow uses regular web search

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_llm_deep
    exclude_tools:
      - web_search_tool             # deep uses advanced web search
```

### Per-Agent Specialization with `exclude_tools`

Use `exclude_tools` to remove specific tools from the inherited set. This is useful when different agents need different variants of a tool (e.g., shallow research uses `web_search_tool` while deep research uses `advanced_web_search_tool`).

### Explicit Override (Backward Compatible)

If an agent specifies an explicit `tools` list, it uses exactly those tools and ignores the registry. This preserves backward compatibility with existing configs:

```yaml
  # Explicit tools list -- registry is NOT used for this agent
  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_llm
    tools:
      - web_search_tool
      - knowledge_search
```

## Disabling a Tool

To disable a tool (for example, to avoid API usage or restrict agents to specific sources), remove it from the `data_source_registry`:

```yaml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: web_search
        name: "Web Search"
        tools:
          - web_search_tool
          - advanced_web_search_tool
      # paper_search removed -- no agent will receive it
```

Since agents inherit from the registry, removing a tool from the registry removes it from all agents. No per-agent config changes needed.

Optionally comment out or remove the tool's function definition in `functions` so the config is clearer.

## Adding New Tools or Data Sources

For guidance on implementing and registering new tools or data sources, refer to:

- [Adding a Tool](../extending/adding-a-tool.md) -- How to create and register a new tool with the NeMo Agent Toolkit.
- [Adding a Data Source](../extending/adding-a-data-source.md) -- How to add a new data source, register it with the data source registry, and use MCP tools as data sources.
