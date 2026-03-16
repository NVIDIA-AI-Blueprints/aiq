<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example: Full Pipeline (LlamaIndex)

The complete AI-Q blueprint configuration using **LlamaIndex + ChromaDB** for knowledge retrieval. This is the recommended setup for local development -- zero external RAG infrastructure required.

This is based on `configs/config_web_default_llamaindex.yml`.

## Configuration

```yaml
# config_web_default_llamaindex.yml (annotated)
# Full pipeline: Web mode with LlamaIndex knowledge layer

# ===========================================================================
# General settings
# ===========================================================================
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
      allow_methods: [GET, POST, DELETE, OPTIONS]
      allow_headers: ["*"]
      allow_credentials: true
      expose_headers: ["*"]

# ===========================================================================
# LLMs
# ===========================================================================
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

  nemotron_nano_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.1
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
  #   temperature: 1.0
  #   top_p: 1.0
  #   max_tokens: 128000
  #   num_retries: 5
  #   chat_template_kwargs:
  #     enable_thinking: true

  # LLM for document summaries (shown in the UI after upload)
  summary_llm:
    _type: nim
    model_name: nvidia/nemotron-mini-4b-instruct
    base_url: "https://integrate.api.nvidia.com/v1"
    api_key: ${NVIDIA_API_KEY}
    temperature: 0.3
    max_tokens: 100

# ===========================================================================
# Functions (tools and agents)
# ===========================================================================
functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true

  # -------------------------------------------------------------------------
  # Knowledge retrieval (LlamaIndex + ChromaDB)
  # -------------------------------------------------------------------------
  # Stores embeddings locally in ChromaDB. No external RAG server needed.
  # Documents are uploaded through the Knowledge API (/v1/collections).
  knowledge_search:
    _type: knowledge_retrieval
    backend: llamaindex
    collection_name: ${COLLECTION_NAME:-test_collection}
    generate_summary: true                                   # Generate per-doc summaries
    summary_model: summary_llm                               # LLM for summaries
    summary_db: ${AIQ_SUMMARY_DB:-sqlite+aiosqlite:///./summaries.db}
    top_k: 5
    chroma_dir: ${AIQ_CHROMA_DIR:-/tmp/chroma_data}          # Local vector store

  # Paper Search (optional - requires SERPER_API_KEY)
  # Uncomment the block below and set SERPER_API_KEY to enable.
  # paper_search_tool:
  #   _type: paper_search
  #   max_results: 5
  #   serper_api_key: ${SERPER_API_KEY}

  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent
    verbose: true
    tools:
      - web_search_tool
      # - paper_search_tool  # Uncomment if SERPER_API_KEY is set
      - knowledge_search

  clarifier_agent:
    _type: clarifier_agent
    llm: nemotron_nano_llm
    planner_llm: nemotron_nano_llm
    tools:
      - web_search_tool
      - knowledge_search
    max_turns: 3
    enable_plan_approval: true
    log_response_max_chars: 2000
    verbose: true

  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_nano_llm
    verbose: true
    tools:
      - web_search_tool
      - knowledge_search
    max_llm_turns: 10
    max_tool_iterations: 5

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_nano_llm  # replace with nemotron_super_llm if available
    max_loops: 2
    verbose: true
    tools:
      # - paper_search_tool  # Uncomment if SERPER_API_KEY is set
      - advanced_web_search_tool
      - knowledge_search

workflow:
  _type: chat_deepresearcher_agent
  verbose: true
  enable_escalation: true
  enable_clarifier: true
  use_async_deep_research: true
  checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}
```

## Required Environment Variables

```bash
# Core (required)
export NVIDIA_API_KEY="nvapi-..."    # pragma: allowlist secret
export TAVILY_API_KEY="tvly-..."     # pragma: allowlist secret
```

No RAG server URLs are needed -- LlamaIndex uses local ChromaDB storage.

## How to Run

### Backend

```bash
source .venv/bin/activate

dotenv -f deploy/.env run .venv/bin/nat serve \
  --config_file configs/config_web_default_llamaindex.yml
```

The server starts at `http://localhost:8000`.

### Frontend (optional)

```bash
cd frontends/ui && npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Upload Documents

```bash
# Create a collection
curl -X POST http://localhost:8000/v1/collections \
  -H "Content-Type: application/json" \
  -d '{"name": "my-docs", "description": "My document collection"}'

# Upload files
curl -X POST http://localhost:8000/v1/collections/my-docs/documents \
  -F "files=@report.pdf"
```

### Ask Questions

```bash
# Submit a query
curl -X POST http://localhost:8000/v1/jobs/async/submit \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "shallow_researcher", "input": "What is CUDA?"}'

# Stream events
curl -N http://localhost:8000/v1/jobs/async/job/{job_id}/stream
```

## Key Differences from Foundational RAG

| Aspect | LlamaIndex (this config) | Foundational RAG |
|--------|--------------------------|------------------|
| Vector store | Local ChromaDB | Hosted RAG server |
| External infra | None | RAG + ingest servers |
| Document summaries | Yes (`generate_summary: true`) | No |
| Best for | Local development | Production multi-user |

For production multi-user deployments, refer to [Full Pipeline -- Foundational RAG](./full-pipeline-web.md).
