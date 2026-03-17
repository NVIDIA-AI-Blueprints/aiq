# Deep Researcher Agent Architecture

This document describes the deep agents implementation using the [LangChain DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview) library for multi-phase research workflows.

## Overview

The deep agents architecture provides a publication-ready research report generation system through an iterative multi-agent workflow. It uses specialized subagents coordinated by an orchestrator to produce comprehensive, cited research reports.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  DeepResearcherAgent                            │
│                 (Orchestrator Agent)                            │
│                  ORCHESTRATOR LLM                               │
│                                                                 │
│  Coordinates subagents in a multi-phase research workflow      │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                           │
        ▼                                           ▼
┌───────────────────────┐             ┌───────────────────────┐
│     planner-agent     │             │   researcher-agent    │
│      PLANNER LLM      │             │    RESEARCHER LLM     │
│                       │             │                       │
│ Content-driven        │             │ Information gathering │
│ research planning -   │             │ - executes search     │
│ iteratively builds    │             │ queries and           │
│ evidence-grounded     │             │ synthesizes relevant  │
│ outlines              │             │ content from sources  │
└───────────────────────┘             └───────────────────────┘
        │                                           │
        └─────────────────────┬─────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Research Tools                            │
│  - Tavily Web Search (tavily_web_search)                        │
│  - Paper search (optional)                                      │
│  - Custom tools via configuration                               │
└─────────────────────────────────────────────────────────────────┘
```

## Middleware Stack

The orchestrator and subagents use middleware for task management and state persistence:

### Orchestrator Middleware

| Middleware | Purpose |
|------------|---------|
| `TodoListMiddleware` | Tracks research tasks and progress |
| `FilesystemMiddleware` | Manages state persistence with configurable backend |
| `EmptyContentFixMiddleware` | Handles empty content from subagents |
| `ModelRetryMiddleware` | Retries model calls with backoff |
| `SubAgentMiddleware` | Coordinates subagent execution and routing |

### Subagent Middleware

Each subagent (planner-agent, researcher-agent) has its own middleware stack:

| Middleware | Purpose |
|------------|---------|
| `TodoListMiddleware` | Tracks subtasks within the subagent |
| `FilesystemMiddleware` | Manages subagent-level state |
| `EmptyContentFixMiddleware` | Handles empty content |
| `ModelRetryMiddleware` | Retries model calls with backoff |

## Workflow Phases

### Phase 1: Research Planning

The **planner-agent** analyzes the user query and generates a structured research plan:

- Creates 4-6 strategic search queries
- Maps queries to report sections
- Builds evidence-grounded outlines through interleaved search and optimization

### Phase 2: Iterative Research

The workflow executes configurable research loops (default: 2):

1. **researcher-agent** executes search queries via configured tools
2. Gathers and synthesizes relevant content from available sources
3. **Orchestrator** creates/updates draft report sections
4. **Orchestrator** analyzes draft and identifies gaps for follow-up queries

### Phase 3: Citation Management

The **orchestrator** catalogs all sources:

- Numbers citations sequentially
- Formats references for the final report

### Phase 4: Final Report

The **orchestrator** produces the polished report:

- Inline citations with numbered references
- Structured sections based on the research plan
- Publication-ready formatting

## Components

### Function: `deep_research_agent`

The core deep research agent using the DeepAgents library.

**Location**: `src/aiq_agent/agents/deep_researcher/`

**Configuration:**

```yaml
functions:
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_nano_llm   # LLM for orchestrator; replace with nemotron_super_llm if available
    researcher_llm: nemotron_nano_llm    # optional; replace with nemotron_super_llm if available
    planner_llm: nemotron_nano_llm        # optional; replace with nemotron_super_llm if available
    max_loops: 2                     # Maximum research iterations
    verbose: true                    # Enable detailed logging
    tools:
      - web_search_tool              # Search tools (e.g. tavily_web_search, paper_search)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `orchestrator_llm` | LLMRef | required | LLM for orchestrator and report generation |
| `researcher_llm` | LLMRef | optional | LLM for researcher subagent; falls back to default if unset |
| `planner_llm` | LLMRef | optional | LLM for planner subagent; falls back to default if unset |
| `tools` | list | `[]` | Research tools (web search, paper search, etc.) |
| `max_loops` | int | `2` | Maximum research iterations |
| `verbose` | bool | `true` | Enable detailed logging |

### Workflow: `deep_research_workflow`

A wrapper workflow that accepts string queries for evaluation and CLI use.

**Configuration:**

```yaml
workflow:
  _type: deep_research_workflow
```

This wrapper:
- Accepts a string query as input
- Converts it to the message format expected by `deep_research_agent`
- Returns the final report as a string

## LLM Roles

The agent uses role-based LLM access via `LLMProvider`:

| Role | Usage | Configured By |
|------|-------|---------------|
| `ORCHESTRATOR` | Orchestrator, final report generation | `orchestrator_llm` config |
| `RESEARCHER` | researcher-agent subagent | `researcher_llm` config (optional; falls back to default) |
| `PLANNER` | planner-agent subagent | `planner_llm` config (optional; falls back to default) |

## Configuration Example

```yaml
general:
  telemetry:
    logging:
      console:
        _type: console
        level: INFO
  use_uvloop: true

llms:
  nemotron_nano_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 1.0
    top_p: 1.0
    max_tokens: 128000
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

functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 10

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_nano_llm  # replace with nemotron_super_llm if available
    max_loops: 2
    tools:
      - web_search_tool

workflow:
  _type: deep_research_workflow
```


## Prompts

The agent loads prompts from `src/aiq_agent/agents/deep_researcher/prompts/`:

| Prompt | Purpose |
|--------|---------|
| `planner.j2` | Instructions for the planning subagent |
| `researcher.j2` | Instructions for the researcher subagent |
| `orchestrator.j2` | Main orchestrator instructions (includes current datetime, clarifier_result, available_documents) |


## State and context

`DeepResearchAgentState` includes optional context passed from the chat researcher workflow:

- **`clarifier_result`**: When the user goes through the clarifier (plan approval) before deep research, the approved plan or clarification log is passed here and injected into the orchestrator prompt.
- **`available_documents`**: User-uploaded documents with summaries; injected into subagent prompts for context.


## Evaluation

### Deep Research Bench (DRB)

The benchmark evaluates research reports using RACE and FACT metrics.

See [frontends/benchmarks/deepresearch_bench/README.md](../../../../frontends/benchmarks/deepresearch_bench/README.md) for full documentation (path from this file to repo root).

**Quick start:**

```bash
# Install the evaluator (from repo root)
uv pip install -e ./frontends/benchmarks/deepresearch_bench

# Run evaluation (use one of the provided configs)
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/deepresearch_bench/configs/config_nemotron_only.yml
```


## References

- [LangChain DeepAgents documentation](https://docs.langchain.com/oss/python/deepagents/overview)
- [NeMo Agent Toolkit documentation](https://docs.nvidia.com/nemo/agent-toolkit/latest/index.html)
- [Deep Research Bench](../../../../frontends/benchmarks/deepresearch_bench/README.md)
