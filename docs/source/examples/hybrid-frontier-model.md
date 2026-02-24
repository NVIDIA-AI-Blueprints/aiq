<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Hybrid Frontier Model

This example uses NVIDIA NIM models for intent classification and shallow research
(fast, low-cost) and a frontier model for deep research (higher quality reports).

## Prerequisites

- `NVIDIA_API_KEY` for NIM models
- `INFERENCE_NVIDIA_API_KEY` for frontier model access through NVIDIA Inference API
- `TAVILY_API_KEY` for web search

## Configuration

```yaml
llms:
  # NIM models for fast paths (intent + shallow)
  nemotron_llm_intent:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.5
    max_tokens: 4096

  nemotron_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.1
    max_tokens: 16384

  # Frontier model for deep research (higher quality)
  frontier_llm:
    _type: openai
    model_name: "azure/openai/gpt-4o"
    api_key: ${INFERENCE_NVIDIA_API_KEY}
    base_url: "https://inference-api.nvidia.com/v1"
    temperature: 1.0
    max_tokens: 128000

functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true

  knowledge_search:
    _type: knowledge_retrieval
    backend: llamaindex
    collection_name: ${COLLECTION_NAME:-test_collection}
    top_k: 5
    chroma_dir: ${AIQ_CHROMA_DIR:-/tmp/chroma_data}

  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent
    tools:
      - web_search_tool
      - knowledge_search

  clarifier_agent:
    _type: clarifier_agent
    llm: nemotron_llm
    planner_llm: nemotron_llm
    tools:
      - web_search_tool
      - knowledge_search
    max_turns: 3
    enable_plan_approval: true

  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_llm
    tools:
      - web_search_tool
      - knowledge_search
    max_llm_turns: 10
    max_tool_iterations: 5

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: frontier_llm    # Frontier model here
    max_loops: 2
    tools:
      - advanced_web_search_tool
      - knowledge_search

workflow:
  _type: chat_deepresearcher_agent
  enable_escalation: true
  enable_clarifier: true
```

## How to Run

Save the configuration above to `configs/config_hybrid_frontier.yml`, then run:

```bash
# Web mode (recommended)
dotenv -f deploy/.env run .venv/bin/nat serve \
  --config_file configs/config_hybrid_frontier.yml

# CLI interactive mode
./scripts/start_cli.sh \
  --config_file configs/config_hybrid_frontier.yml
```

## How It Works

The hybrid setup keeps shallow queries fast and cheap (NIM models respond in seconds) while
routing complex deep research to a frontier model that produces higher-quality reports.

The `openai` LLM type with `base_url: "https://inference-api.nvidia.com/v1"` routes through
NVIDIA's Inference API, which provides access to frontier models. You need an
`INFERENCE_NVIDIA_API_KEY` -- refer to [NVIDIA Inference API](https://build.nvidia.com/) to obtain one.