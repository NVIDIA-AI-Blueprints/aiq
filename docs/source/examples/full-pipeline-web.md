<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example: Full Pipeline (Foundational RAG)

The complete AI-Q blueprint configuration with all features enabled: intent classification, shallow and deep research agents, knowledge retrieval (Foundational RAG), paper search, web search, clarifier with human-in-the-loop plan approval, and the async jobs API with SSE streaming.

This is based on `configs/config_web_frag.yml`, which is the default for Helm deployments.

## Configuration

```yaml
# config_web_frag.yml (annotated)
# Full pipeline: Web mode with Foundational RAG knowledge layer

# ===========================================================================
# General settings
# ===========================================================================
general:
  use_uvloop: true  # Use uvloop for better async performance (Linux/macOS)

  telemetry:
    logging:
      console:
        _type: console
        level: INFO
    # Uncomment for tracing:
    # tracing:
    #   phoenix:
    #     _type: phoenix
    #     endpoint: http://localhost:6006/v1/traces
    #     project: dev

  # ---------------------------------------------------------------------------
  # Front-end: AI-Q API plugin
  # ---------------------------------------------------------------------------
  # This enables the async jobs API, SSE streaming, and Knowledge API.
  # Without this section, `nat serve` uses NeMo Agent Toolkit's default WebSocket front-end.
  front_end:
    _type: aiq_api
    runner_class: aiq_api.plugin.AIQAPIWorker

    # Async job database (JobStore + EventStore)
    # SQLite for local dev, PostgreSQL for production
    db_url: ${NAT_JOB_STORE_DB_URL:-sqlite+aiosqlite:///./jobs.db}

    # Completed jobs are cleaned up after this duration
    expiry_seconds: 86400  # 24 hours (range: 600 to 604800)

    # CORS settings for the frontend UI
    cors:
      allow_origin_regex: 'http://localhost(:\d+)?|http://127.0.0.1(:\d+)?'
      allow_methods: [GET, POST, DELETE, OPTIONS]
      allow_headers: ["*"]
      allow_credentials: true
      expose_headers: ["*"]

# ===========================================================================
# LLMs
# ===========================================================================
# Three LLM configurations for different roles:
# - Intent classification (moderate creativity for routing decisions)
# - Research (low temperature for factual output)
# - Deep research orchestrator (high temperature for diverse planning)
llms:
  nemotron_llm_intent:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.5    # Moderate: needs to reason about intent
    top_p: 0.9
    max_tokens: 4096
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

  nemotron_nano_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.1    # Low: factual research output
    top_p: 0.3
    max_tokens: 16384
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

  # Nemotron Super is compatible and tested with AIQ but has limited availability
  # on the Build API due to high demand.
  # Uncomment nemotron_super_llm below if the endpoint is accessible.
  # nemotron_super_llm:
  #   _type: nim
  #   model_name: nvidia/nemotron-3-super-120b-a12b
  #   base_url: "https://integrate.api.nvidia.com/v1"
  #   temperature: 1.0    # High: diverse research planning
  #   top_p: 1.0
  #   max_tokens: 128000  # Large context for multi-loop orchestration
  #   num_retries: 5
  #   chat_template_kwargs:
  #     enable_thinking: true

# ===========================================================================
# Functions (tools and agents)
# ===========================================================================
functions:
  # -------------------------------------------------------------------------
  # Search tools
  # -------------------------------------------------------------------------
  web_search_tool:
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true   # Full page content extraction

  paper_search_tool:
    _type: paper_search
    max_results: 5
    serper_api_key: ${SERPER_API_KEY}

  # -------------------------------------------------------------------------
  # Knowledge retrieval (Foundational RAG)
  # -------------------------------------------------------------------------
  # This enables the Knowledge API endpoints (/v1/collections, /v1/documents)
  # and gives agents access to uploaded document collections.
  knowledge_search:
    _type: knowledge_retrieval
    backend: foundational_rag
    collection_name: ${COLLECTION_NAME:-test_collection}
    top_k: 5
    rag_url: ${RAG_SERVER_URL:-http://localhost:8081}
    ingest_url: ${RAG_INGEST_URL:-http://localhost:8082}
    timeout: 300

  # -------------------------------------------------------------------------
  # Intent classifier
  # -------------------------------------------------------------------------
  # Routes queries to shallow or deep research based on complexity.
  # Has access to tools for context-aware routing decisions.
  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent
    tools:
      - web_search_tool
      - paper_search_tool
      - knowledge_search

  # -------------------------------------------------------------------------
  # Clarifier agent (human-in-the-loop)
  # -------------------------------------------------------------------------
  # For deep research: asks clarifying questions and generates a research
  # plan that the user can approve or modify before execution.
  clarifier_agent:
    _type: clarifier_agent
    llm: nemotron_nano_llm
    planner_llm: nemotron_nano_llm
    tools:
      - web_search_tool
      - knowledge_search
    max_turns: 3                  # Max clarification rounds
    enable_plan_approval: true    # User must approve the plan
    log_response_max_chars: 2000
    verbose: true

  # -------------------------------------------------------------------------
  # Shallow research agent
  # -------------------------------------------------------------------------
  # Single-turn ReAct agent for quick queries.
  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_nano_llm
    tools:
      - web_search_tool
      - knowledge_search
    max_llm_turns: 10
    max_tool_iterations: 5

  # -------------------------------------------------------------------------
  # Deep research agent
  # -------------------------------------------------------------------------
  # Multi-loop orchestrator that plans research, delegates to sub-agents,
  # and synthesizes comprehensive reports.
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_nano_llm  # replace with nemotron_super_llm if available
    max_loops: 2                  # Research iteration loops
    tools:
      - paper_search_tool
      - advanced_web_search_tool
      - knowledge_search

# ===========================================================================
# Workflow
# ===========================================================================
# The chat_deepresearcher_agent is the meta-routing workflow:
# 1. Intent classifier determines shallow vs deep
# 2. Shallow queries go directly to shallow_research_agent
# 3. Deep queries go through clarifier -> plan approval -> deep_research_agent
workflow:
  _type: chat_deepresearcher_agent
  enable_escalation: true          # Allow shallow -> deep escalation
  enable_clarifier: true           # Enable clarification flow for deep research
  use_async_deep_research: true    # Run deep research asynchronously
  checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}
```

## Required Environment Variables

```bash
# Core (required)
export NVIDIA_API_KEY="nvapi-..."    # pragma: allowlist secret
export TAVILY_API_KEY="tvly-..."     # pragma: allowlist secret
export SERPER_API_KEY="..."

# Knowledge layer (required if using Foundational RAG)
export RAG_SERVER_URL="http://localhost:8081"
export RAG_INGEST_URL="http://localhost:8082"

# Optional: production database
# export NAT_JOB_STORE_DB_URL="postgresql+asyncpg://user:pass@host:5432/aiq_jobs"  # pragma: allowlist secret
```

## How to Run

### Local Development

```bash
dotenv -f deploy/.env run .venv/bin/nat serve \
  --config_file configs/config_web_frag.yml
```

The server starts at `http://localhost:8000`. The API docs are at `http://localhost:8000/docs`.

### Docker Compose

```bash
cd deploy
cp .env.example .env
# Edit .env with your API keys and set:
# BACKEND_CONFIG=/app/configs/config_web_frag.yml
docker compose up
```

### Test the Pipeline

```bash
# List available agents
curl http://localhost:8000/v1/jobs/async/agents

# Submit a shallow query
curl -X POST http://localhost:8000/v1/jobs/async/submit \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "shallow_researcher", "input": "What is CUDA?"}'

# Submit a deep research query
curl -X POST http://localhost:8000/v1/jobs/async/submit \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "deep_researcher", "input": "Compare transformer architectures for long-context inference"}'

# Stream events
curl -N http://localhost:8000/v1/jobs/async/job/{job_id}/stream

# Get the final report
curl http://localhost:8000/v1/jobs/async/job/{job_id}/report
```

## All Features Enabled

This configuration enables every major feature:

| Feature | Config Key | Status |
|---------|-----------|--------|
| Intent classification | `intent_classifier` | Enabled |
| Shallow research | `shallow_research_agent` | Enabled |
| Deep research | `deep_research_agent` | Enabled |
| Clarifier (HITL) | `clarifier_agent` + `enable_clarifier: true` | Enabled |
| Research escalation | `enable_escalation: true` | Enabled |
| Web search | `web_search_tool`, `advanced_web_search_tool` | Enabled |
| Paper search | `paper_search_tool` | Enabled |
| Knowledge layer | `knowledge_search` (Foundational RAG) | Enabled |
| Async jobs API | `front_end._type: aiq_api` | Enabled |
| SSE streaming | Automatic with `aiq_api` | Enabled |
| Knowledge API | Automatic when `knowledge_retrieval` configured | Enabled |
| Conversation persistence | `checkpoint_db` | Enabled |
