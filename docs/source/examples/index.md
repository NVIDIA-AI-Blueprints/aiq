<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Examples

Complete, annotated configuration examples for common use cases.

| Example | Description | Config base |
|---------|-------------|-------------|
| [Minimal Shallow Only](./minimal-shallow-only.md) | Simplest setup — shallow research with web search | Custom minimal |
| [Full Pipeline -- LlamaIndex](./full-pipeline-llamaindex.md) | Complete local setup with LlamaIndex + ChromaDB | `config_web_default_llamaindex.yml` |
| [Full Pipeline -- Foundational RAG](./full-pipeline-web.md) | Complete production setup with hosted RAG | `config_web_frag.yml` |
| [Azure AI Search Knowledge Layer](./azure-ai-search.md) | Managed hybrid document retrieval | `config_web_azure_ai_search.yml` |
| [CLI with Local NIMs](./cli-with-local-nims.md) | Interactive CLI mode with self-hosted NIM models | `config_cli_default.yml` |
| [Hybrid Frontier Model](./hybrid-frontier-model.md) | NIM for shallow + frontier model for deep research | Custom hybrid |
| [Deep Research Skills and Sandbox](./skills-sandbox/index.md) | DeepAgents skills with provider-backed sandbox execution for quantitative research workflows | `config_domain_routing_and_skills.yml` |
