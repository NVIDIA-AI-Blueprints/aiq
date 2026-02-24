<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# FAQ

Frequently asked questions about the AI-Q blueprint.

## General

**What is the AI-Q blueprint?**

An NVIDIA blueprint for AI-powered deep research built on the NeMo Agent Toolkit. It combines intelligent query routing, multi-agent research pipelines, and pluggable knowledge retrieval to deliver comprehensive, citation-backed research answers.

**What models does it use?**

By default, it uses NVIDIA NIM models (for example, Nemotron) through the `integrate.api.nvidia.com` API. You can swap to any NIM-compatible model, self-hosted NIMs, or other LLM providers. Refer to [Swapping Models](../customization/swapping-models.md).

**Do I need a GPU?**

Not for running the blueprint itself — it calls cloud-hosted LLM APIs. You only need a GPU if you self-host NIM models locally. Refer to [Using Downloadable NIMs](../customization/swapping-models.md#using-downloadable-nims-self-hosted).

## Architecture

**What's the difference between shallow and deep research?**

- **Shallow research** is fast (30-60s), uses a single agent with bounded tool calls, and produces concise answers with citations. Best for simple factual queries.
- **Deep research** is thorough (2-10min), uses a multi-agent pipeline (planner + researcher + orchestrator), and produces comprehensive reports with structured sections and numbered references. Best for complex multi-faceted topics.

The [Intent Classifier](../architecture/agents/intent-classifier.md) automatically routes queries to the appropriate depth.

**Can I disable the clarifier / plan approval step?**

Yes. Refer to [Human-in-the-Loop](../customization/hitl.md) for configuration options. You can disable the clarifier entirely or keep it but skip plan approval.

**What happens when shallow research escalates to deep?**

If `enable_escalation: true` in the workflow config, the orchestrator evaluates the shallow research result. If it detects insufficient coverage (response too short, "unable to find" keywords), it escalates to the clarifier and then deep research. Refer to [Architecture Overview](../architecture/overview.md).

## Tools and Sources

**What search tools are available?**

- **Tavily Web Search** — General web search (requires `TAVILY_API_KEY`)
- **Google Scholar Paper Search** — Academic paper search (requires `SERPER_API_KEY`)
- **Knowledge Layer** — Document retrieval from local or hosted vector stores

Refer to [Tools and Sources](../customization/tools-and-sources.md).

**Can I add my own tools?**

Yes. Refer to [Adding a Tool](../extending/adding-a-tool.md) for an end-to-end guide on building and registering custom NeMo Agent Toolkit functions.

## Knowledge Layer

**Which knowledge layer backend should I use?**

- **LlamaIndex** (ChromaDB) for development and prototyping — runs locally, no external services needed
- **Foundational RAG** for production — connects to NVIDIA RAG Blueprint, supports multi-user with Milvus

Refer to [Knowledge Layer](../customization/knowledge-layer.md).

**How do I upload documents?**

Through the Web UI (drag and drop), the Knowledge API (`POST /v1/collections/{name}/documents`), or programmatically through the ingestor SDK. Refer to [Knowledge Layer](../customization/knowledge-layer.md#web-ui-mode).

## Deployment

**What are the deployment options?**

1. **Local development** — `nat run` or `nat serve` directly
2. **Docker Compose** — Full stack with backend, frontend, and database

Refer to [Deployment](../deployment/index.md).

**What database should I use in production?**

PostgreSQL. The default compose stack includes a PostgreSQL container. For production, use a managed database service. Refer to [Deployment — Production Considerations](../deployment/production.md).

## Evaluation

**How do I measure research quality?**

Use the built-in benchmark suites: FreshQA (factual accuracy), Deep Research Bench (report quality), DeepSearchQA (document QA), and Intent Classifier (routing accuracy). Refer to [Benchmarks](../evaluation/benchmarks/index.md).

**How do I run benchmarks?**

```bash
dotenv -f deploy/.env run .venv/bin/nat eval --config_file frontends/benchmarks/freshqa/configs/config_shallow_research_only.yml
```

Refer to each benchmark's documentation for config options and methodology.
