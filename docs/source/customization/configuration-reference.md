<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Configuration Reference

The AI-Q blueprint is configured through a single YAML file that defines LLMs, tools, agents, and the workflow. The NeMo Agent Toolkit reads this file at startup and wires everything together.

## Config File Structure

Every config file has four top-level sections:

```yaml
general:     # Telemetry, logging, front-end settings
llms:        # LLM definitions (model, endpoint, parameters)
functions:   # Tools and agents (search tools, classifiers, research agents)
workflow:    # Top-level orchestrator configuration
```

## Environment Variable Substitution

You can reference environment variables anywhere in the YAML using shell-style syntax:

```yaml
# Required variable (fails if not set)
api_key: ${NVIDIA_API_KEY}

# Variable with a default value
checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}

# Nested in a URL
collection_name: ${COLLECTION_NAME:-test_collection}
```

The syntax `${VAR_NAME}` substitutes the value of the environment variable. The syntax `${VAR_NAME:-default}` provides a fallback value if the variable is not set. Environment variables are typically defined in `deploy/.env` or `.env` at the project root.

---

## `general` Section

Controls telemetry, logging, and the application front-end.

```yaml
general:
  use_uvloop: true          # Use uvloop for better async performance (web mode)
  telemetry:
    logging:
      console:
        _type: console
        level: INFO          # DEBUG, INFO, WARNING, ERROR
    tracing:
      phoenix:               # Optional: Phoenix observability
        _type: phoenix
        endpoint: http://localhost:6006/v1/traces
        project: dev
  front_end:                 # Only for web/API mode
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
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `use_uvloop` | `bool` | `false` | Enable uvloop for improved async I/O performance. Recommended for web mode. |
| `telemetry.logging.console._type` | `str` | `console` | Logging backend type. |
| `telemetry.logging.console.level` | `str` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `telemetry.tracing` | `object` | -- | Optional tracing configuration (Phoenix, OpenTelemetry). |
| `front_end._type` | `str` | -- | Front-end type. Use `aiq_api` for the web API server. Omit for CLI mode. |
| `front_end.db_url` | `str` | `sqlite+aiosqlite:///./jobs.db` | Database URL for async job persistence. |
| `front_end.expiry_seconds` | `int` | `86400` | How long completed jobs remain in the database (seconds). |
| `front_end.cors` | `object` | -- | CORS settings for the API server. |

---

## `llms` Section

Defines named LLM instances. Each entry gets a user-chosen key (for example, `nemotron_nano_llm`) that agents reference.

```yaml
llms:
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
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `_type` | `str` | **required** | LLM provider type. Use `nim` for NVIDIA NIM endpoints, `openai` for OpenAI-compatible endpoints. |
| `model_name` | `str` | **required** | Model identifier (for example, `nvidia/nemotron-3-nano-30b-a3b`, `azure/openai/gpt-4.1-mini`). |
| `base_url` | `str` | `None` | API endpoint URL. Should always be set explicitly for NVIDIA NIM endpoints. |
| `api_key` | `str` | -- | API key. If omitted, uses `NVIDIA_API_KEY` from the environment. |
| `temperature` | `float` | `None` | Sampling temperature. Lower values produce more deterministic output. When `None`, the API uses its server-side default. |
| `top_p` | `float` | `None` | Nucleus sampling threshold. When `None`, the API uses its server-side default. |
| `max_tokens` | `int` | `300` | Maximum tokens in the response. Set higher values (for example, `16384` or `128000`) for research agents. |
| `num_retries` | `int` | `5` | Number of retry attempts on API failure. |
| `chat_template_kwargs` | `object` | -- | Extra arguments passed to the chat template. Use `enable_thinking: true` to activate the model's chain-of-thought reasoning. |

### Common LLM Configurations

Different agents benefit from different parameter profiles:

| Role | Temperature | Top-p | Max Tokens | Notes |
|------|------------|-------|------------|-------|
| Intent classifier | `0.5` | `0.9` | `4096` | Moderate creativity for classification |
| Shallow researcher | `0.1` | `0.3` | `16384` | Low temperature for factual accuracy |
| Deep research orchestrator | `1.0` | `1.0` | `128000` | High temperature with thinking enabled for deep reasoning |
| Summary LLM | `0.3` | -- | `100` | Conservative, short output for document summaries |

---

## `functions` Section

Defines tools and agents. Each entry has a `_type` field that maps to a registered NeMo Agent Toolkit plugin. The key you assign (for example, `web_search_tool`) becomes the name used in `tools` lists.

### `tavily_web_search`

Web search powered by the [Tavily API](https://tavily.com/).

```yaml
functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_results` | `int` | `3` | Maximum number of search results to return. |
| `include_answer` | `str` | `"advanced"` | Whether to include a synthesized answer alongside search results. Tavily returns a direct answer in addition to individual result documents. |
| `api_key` | `str` | `None` | Tavily API key. Falls back to `TAVILY_API_KEY` environment variable. |
| `max_retries` | `int` | `3` | Number of retry attempts on search failure. |
| `advanced_search` | `bool` | `false` | Use Tavily's advanced search mode for deeper, more thorough results. |
| `max_content_length` | `int` | `None` | Truncate each result's content to this many characters. Reduces token usage. |

### `paper_search`

Academic paper search through Google Scholar (using the [Serper API](https://serper.dev/)).

```yaml
functions:
  paper_search_tool:
    _type: paper_search
    max_results: 5
    serper_api_key: ${SERPER_API_KEY}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_results` | `int` | `10` | Maximum number of paper results. |
| `serper_api_key` | `str` | `None` | Serper API key. Falls back to `SERPER_API_KEY` environment variable. |
| `timeout` | `int` | `30` | Timeout in seconds for search requests. |

### `knowledge_retrieval`

Semantic search over ingested documents. Supports two backends: LlamaIndex (local ChromaDB) and Foundational RAG (hosted NVIDIA RAG Blueprint).

```yaml
functions:
  # LlamaIndex backend
  knowledge_search:
    _type: knowledge_retrieval
    backend: llamaindex
    collection_name: ${COLLECTION_NAME:-test_collection}
    top_k: 5
    chroma_dir: ${AIQ_CHROMA_DIR:-/tmp/chroma_data}
    generate_summary: true
    summary_model: summary_llm
    summary_db: ${AIQ_SUMMARY_DB:-sqlite+aiosqlite:///./summaries.db}
```

```yaml
functions:
  # Foundational RAG backend
  knowledge_search:
    _type: knowledge_retrieval
    backend: foundational_rag
    collection_name: ${COLLECTION_NAME:-test_collection}
    top_k: 5
    rag_url: ${RAG_SERVER_URL:-http://localhost:8081/v1}
    ingest_url: ${RAG_INGEST_URL:-http://localhost:8082/v1}
    timeout: 300
    # verify_ssl: false            # Only set to false for self-signed certs
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | `str` | `llamaindex` | Backend type: `llamaindex` or `foundational_rag`. |
| `collection_name` | `str` | `default` | Name of the document collection/index. |
| `top_k` | `int` | `5` | Number of results to return per query. |
| `generate_summary` | `bool` | `false` | Generate one-sentence summaries for ingested documents. |
| `summary_model` | `str` | `None` | LLM reference from `llms` section. Required when `generate_summary: true`. |
| `summary_db` | `str` | `sqlite+aiosqlite:///./summaries.db` | Database URL for document summaries (SQLite or PostgreSQL). |
| `chroma_dir` | `str` | `/tmp/chroma_data` | ChromaDB persistence directory. LlamaIndex backend only. |
| `rag_url` | `str` | `http://localhost:8081/v1` | RAG query server URL. Foundational RAG backend only. |
| `ingest_url` | `str` | `http://localhost:8082/v1` | RAG ingestion server URL. Foundational RAG backend only. |
| `timeout` | `int` | `120` | Request timeout in seconds. Foundational RAG backend only. |
| `verify_ssl` | `bool` | `true` | Verify SSL certificates. Set `false` for self-signed certs. Foundational RAG backend only. |

### `intent_classifier`

Classifies user queries as meta (conversational) or research, and determines research depth (shallow vs. deep).

```yaml
functions:
  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent
    tools:
      - web_search_tool
      - paper_search_tool
    verbose: true
    llm_timeout: 90
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm` | `str` | **required** | Reference to an LLM defined in `llms` section. |
| `tools` | `list[str]` | `[]` | Tool references passed to the intent prompt for tool-awareness. |
| `verbose` | `bool` | `false` | Enable verbose logging with trace callbacks. |
| `llm_timeout` | `float` | `90` | Timeout in seconds for the intent classification LLM call. |

### `clarifier_agent`

Interactive clarification dialog for deep research queries. Asks follow-up questions to refine scope before research begins.

```yaml
functions:
  clarifier_agent:
    _type: clarifier_agent
    llm: nemotron_llm
    planner_llm: nemotron_llm
    tools:
      - web_search_tool
    max_turns: 3
    enable_plan_approval: true
    max_plan_iterations: 10
    log_response_max_chars: 2000
    verbose: true
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm` | `str` | **required** | LLM for generating clarification questions. |
| `planner_llm` | `str` | `None` | LLM for plan generation. Falls back to `llm` if not specified. |
| `tools` | `list[str]` | `[]` | Tools available for gathering context during clarification. |
| `max_turns` | `int` | `3` | Maximum number of clarification Q&A turns before auto-completing. |
| `enable_plan_approval` | `bool` | `false` | Show research plan to the user for approval after clarification. |
| `max_plan_iterations` | `int` | `10` | Maximum plan feedback iterations before auto-approving. |
| `log_response_max_chars` | `int` | `2000` | Maximum characters to log from LLM responses. |
| `verbose` | `bool` | `false` | Enable verbose logging. |

### `shallow_research_agent`

Fast, single-pass research agent that produces citation-backed answers in one tool-calling loop.

```yaml
functions:
  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_llm
    tools:
      - web_search_tool
      - knowledge_search
    max_llm_turns: 10
    max_tool_iterations: 5
    verbose: true
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm` | `str` | **required** | LLM for research and synthesis. |
| `tools` | `list[str]` | `[]` | Search tools available to the agent. |
| `max_llm_turns` | `int` | `10` | Maximum number of LLM turns (includes both reasoning and tool-calling steps). |
| `max_tool_iterations` | `int` | `5` | Maximum tool-calling iterations before forcing synthesis. |
| `verbose` | `bool` | `false` | Enable verbose logging. |

### `deep_research_agent`

Multi-phase research agent with separate orchestrator, planner, and researcher sub-agents that produces long-form reports.

```yaml
functions:
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_nano_llm  # replace with nemotron_super_llm if available
    researcher_llm: nemotron_nano_llm  # replace with nemotron_super_llm if available
    planner_llm: nemotron_nano_llm  # replace with nemotron_super_llm if available
    tools:
      - paper_search_tool
      - advanced_web_search_tool
      - knowledge_search
    max_loops: 2
    verbose: true
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `orchestrator_llm` | `str` | **required** | LLM for the orchestrator that coordinates the research workflow. |
| `researcher_llm` | `str` | `None` | LLM for the researcher sub-agent. Falls back to `orchestrator_llm` if not specified. |
| `planner_llm` | `str` | `None` | LLM for the planner sub-agent. Falls back to `orchestrator_llm` if not specified. |
| `tools` | `list[str]` | `[]` | Search tools available to the researcher sub-agent. |
| `max_loops` | `int` | `2` | Maximum number of orchestrator planning/research loops. |
| `verbose` | `bool` | `true` | Enable verbose logging. |

---

## `workflow` Section

Defines the top-level orchestrator that wires together all agents.

```yaml
workflow:
  _type: chat_deepresearcher_agent
  enable_escalation: true
  enable_clarifier: true
  use_async_deep_research: true
  max_history: 20
  verbose: true
  checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `_type` | `str` | **required** | Workflow type. Use `chat_deepresearcher_agent` for the full pipeline. |
| `enable_escalation` | `bool` | `true` | Allow the intent classifier to route queries to deep research. When `false`, all research queries use shallow research only. |
| `enable_clarifier` | `bool` | `true` | Run the clarifier agent before deep research to gather user requirements. |
| `use_async_deep_research` | `bool` | `false` | Submit deep research as an async background job (requires [Dask](https://www.dask.org/) scheduler). |
| `max_history` | `int` | `20` | Maximum number of messages to keep in conversation history before trimming. |
| `verbose` | `bool` | `false` | Enable verbose logging. |
| `checkpoint_db` | `str` | `./checkpoints.db` | SQLite path or PostgreSQL DSN for persistent conversation checkpoints. |

> **Note:** `interactive_auth` is a YAML-level field consumed by the CLI entry point (`start_cli.sh` / `aiq-research`), not a Pydantic field on `ChatDeepResearcherConfig`. It can be set in YAML config files but is not part of the workflow config class.

---

## Complete Annotated Example

Below is a complete configuration for CLI mode with web search, paper search, and clarification enabled:

```yaml
# General settings
general:
  telemetry:
    logging:
      console:
        _type: console
        level: INFO                    # Set to DEBUG for troubleshooting

# LLM definitions
llms:
  intent_llm:                          # Used by intent classifier
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.5
    top_p: 0.9
    max_tokens: 4096
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

  research_llm:                        # Used by shallow researcher + clarifier
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.1
    top_p: 0.3
    max_tokens: 16384
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

  deep_llm:                            # Used by deep research orchestrator
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 1.0
    top_p: 1.0
    max_tokens: 128000
    num_retries: 5
    chat_template_kwargs:
      enable_thinking: true

# Tools and agents
functions:
  web_search_tool:                     # Standard web search
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:            # Deep search (fewer results, more depth)
    _type: tavily_web_search
    max_results: 2
    advanced_search: true

  paper_search_tool:                   # Academic paper search
    _type: paper_search
    max_results: 5
    serper_api_key: ${SERPER_API_KEY}

  intent_classifier:                   # Classifies queries, routes depth
    _type: intent_classifier
    llm: intent_llm
    tools:
      - web_search_tool
      - paper_search_tool

  clarifier_agent:                     # Asks clarifying questions for deep research
    _type: clarifier_agent
    llm: research_llm
    planner_llm: research_llm
    tools:
      - web_search_tool
    max_turns: 3
    enable_plan_approval: true
    verbose: true

  shallow_research_agent:              # Fast single-pass research
    _type: shallow_research_agent
    llm: research_llm
    tools:
      - web_search_tool
    max_llm_turns: 10
    max_tool_iterations: 5

  deep_research_agent:                 # Multi-phase deep research
    _type: deep_research_agent
    orchestrator_llm: deep_llm
    tools:
      - paper_search_tool
      - advanced_web_search_tool
    max_loops: 2

# Top-level orchestrator
workflow:
  _type: chat_deepresearcher_agent
  enable_escalation: true              # Allow deep research routing
  enable_clarifier: true               # Ask clarifying questions first
  checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}
```

## Provided Config Files

The repository includes several pre-built configurations:

| File | Mode | Features |
|------|------|----------|
| `configs/config_cli_default.yml` | CLI | Web search, paper search, clarifier with plan approval |
| `configs/config_web_default_llamaindex.yml` | Web API | LlamaIndex knowledge retrieval, web search, paper search |
| `configs/config_web_frag.yml` | Web API | Foundational RAG knowledge retrieval, web search, paper search |

## Related

- [Swapping Models](./swapping-models.md) -- Change LLMs without touching agent code
- [Tools and Sources](./tools-and-sources.md) -- Enable and disable search tools
- [Knowledge Layer](./knowledge-layer.md) -- Configure document retrieval backends
- [Prompts](./prompts.md) -- Customize agent behavior through prompt templates
