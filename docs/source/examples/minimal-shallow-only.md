<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example: Minimal Shallow Research

The simplest possible configuration: a single shallow research agent with web search. No deep research, no intent classification, no knowledge layer, no authentication.

This is a good starting point for understanding the config structure before adding complexity.

## Configuration

```yaml
# minimal_shallow.yml
# Minimal config: shallow research agent + Tavily web search only

general:
  telemetry:
    logging:
      console:
        _type: console
        level: INFO

# ---------------------------------------------------------------------------
# LLMs
# ---------------------------------------------------------------------------
# A single LLM is sufficient for shallow research. The NIM type connects to
# NVIDIA's hosted inference endpoint. Adjust temperature for creativity vs
# factuality trade-off.
llms:
  research_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.1       # Low temperature for factual research
    top_p: 0.3
    max_tokens: 16384      # Max output length per LLM call
    num_retries: 5         # Retry on transient API failures
    chat_template_kwargs:
      enable_thinking: true  # Enable chain-of-thought reasoning

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
# The shallow researcher calls tools in a ReAct loop. At minimum, it needs
# one search tool to gather information from the web.
functions:
  web_search:
    _type: tavily_web_search
    max_results: 5              # Number of search results per query
    max_content_length: 1000    # Truncate each result to this many chars

  # The shallow research agent itself
  shallow_research_agent:
    _type: shallow_research_agent
    llm: research_llm
    tools:
      - web_search
    max_llm_turns: 10    # Max reasoning steps before forced output
    max_tool_iterations: 5    # Max tool invocations per session

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
# Use the shallow_research_agent directly as the workflow entry point.
# This bypasses the chat_deepresearcher routing and runs shallow research
# on every query.
workflow:
  _type: shallow_research_agent
```

## Required Environment Variables

```bash
export NVIDIA_API_KEY="nvapi-..."    # pragma: allowlist secret
export TAVILY_API_KEY="tvly-..."     # pragma: allowlist secret
```

## How to Run

### CLI Mode

Save the configuration above to `configs/minimal_shallow.yml`, then run:

```bash
# Interactive mode
./scripts/start_cli.sh --config_file configs/minimal_shallow.yml

# Single query mode
dotenv -f deploy/.env run .venv/bin/nat run \
  --config_file configs/minimal_shallow.yml \
  --input "What is quantum error correction?"
```

### Web Mode (API server)

To serve the shallow researcher over HTTP, add a `front_end` section:

```yaml
general:
  front_end:
    _type: aiq_api
    runner_class: aiq_api.plugin.AIQAPIWorker
    db_url: sqlite+aiosqlite:///./jobs.db
    expiry_seconds: 86400
  telemetry:
    logging:
      console:
        _type: console
        level: INFO
```

Then run:

```bash
dotenv -f deploy/.env run .venv/bin/nat serve \
  --config_file configs/minimal_shallow.yml
```

Submit a query:

```bash
curl -X POST http://localhost:8000/v1/jobs/async/submit \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "shallow_researcher", "input": "What is quantum error correction?"}'
```

## What to Expect

1. The shallow researcher receives your query
2. It enters a ReAct loop: **think** (reason about what to search) then **act** (call `web_search`)
3. After gathering enough information (up to 5 tool calls), it synthesizes a research report
4. The final output is a structured markdown report with inline citations

**Typical execution:** 3--5 tool calls, 15--30 seconds total (depending on model and search latency).

The shallow researcher is optimized for speed over depth. For multi-loop, comprehensive research, refer to the [Full Pipeline (Web)](./full-pipeline-web.md) example.