<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Tools and Sources

Some tools and data sources are **enabled** by being listed in the workflow and in each agent's `tools` list. They are **disabled** by omitting them from those lists (you can leave or remove the function definition in `functions`; if nothing references it, it won't be used).

## Disabling a Tool

**Example: disabling the paper search tool**

To disable the paper search tool (for example, to avoid Serper/API usage or to restrict agents to web search only), remove `paper_search_tool` from every `tools` list that references it. For example, in `config_cli_default.yml` you would:

1. Remove `paper_search_tool` from `intent_classifier.tools` (orchestration node).
2. Remove `paper_search_tool` from `deep_research_agent.tools`.
3. Optionally comment out or remove the `paper_search_tool` function block in `functions` so the config is clearer.

**Before (paper search enabled):**

```yaml
functions:
  intent_classifier:
    _type: intent_classifier
    tools:
      - web_search_tool
      - paper_search_tool

  deep_research_agent:
    _type: deep_research_agent
    tools:
      - paper_search_tool
      - advanced_web_search_tool
```

**After (paper search disabled):**

```yaml
functions:
  intent_classifier:
    _type: intent_classifier
    tools:
      - web_search_tool

  deep_research_agent:
    _type: deep_research_agent
    tools:
      - advanced_web_search_tool
```

The same idea applies to any other tool or data source: include it in the relevant `tools` lists to enable it, remove it to disable it.

## Adding New Tools or Data Sources

For guidance on implementing and registering new tools or data sources, refer to:

- [Adding a Tool](../extending/adding-a-tool.md) -- How to create and register a new tool with the NeMo Agent Toolkit.
- [Adding a Data Source](../extending/adding-a-data-source.md) -- How to add a new data source or knowledge layer backend.
