<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

-->
<h1>NVIDIA AI-Q Blueprint</h1>

> **IMPORTANT**
>
> **Active Development Branch**
> You are viewing the **`develop`** branch. This branch contains the latest features and experimental updates. For the most stable enterprise-ready version, please switch to the [main branch](https://github.com/NVIDIA-AI-Blueprints/aiq/tree/main).

## Table of Contents 
- [Overview](#overview)
- [Software Components](#software-components)
- [Target Audience](#target-audience)
- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
  - [Clone the Repository](#clone-the-repository)
  - [Automated Setup](#automated-setup)
  - [Obtain API Keys](#obtain-api-keys)
  - [Set Up Environment Variables](#set-up-environment-variables)
- [Ways to Run the Agents](#ways-to-run-the-agents)
  - [Command-line interface (CLI)](#command-line-interface-cli)
  - [Web UI](#web-ui)
  - [Async Deep Research Jobs](#async-deep-research-jobs)
  - [Benchmarks](#benchmarks)
- [Evaluating the Workflow](#evaluating-the-workflow)
  - [Available Benchmarks](#available-benchmarks)
  - [Running Evaluations](#running-evaluations)
- [Development](#development)
- [License](#license)

## Overview

The NVIDIA AI-Q Blueprint is an enterprise-grade research agent built on the [NVIDIA NeMo Agent Toolkit](https://docs.nvidia.com/nemo/agent-toolkit/latest/). It gives you both **quick, cited answers** and **in-depth, report-style research** in one system, with benchmarks and evaluation harnesses so you can measure quality and improve over time.

<p align="center">
<img src="./docs/assets/AIQ-arch-light.png" alt="AI-Q Architecture" width="800">
</p>

**Key features:**

- **Orchestration node** — One node classifies intent (meta vs. research), produces meta responses (for example, greetings, capabilities), and sets research depth (shallow vs. deep).
- **Shallow research** — Bounded, faster researcher with tool-calling and source citation.
- **Deep research** — Long-running multi-step planning and research to generate a long-form citation-backed report.
- **Workflow configuration** — YAML configs define agents, tools, LLMs, and routing behavior so you can tune workflows without code changes.
- **Modular workflows** — All agents (orchestration node, shallow researcher, deep researcher, clarifier) are composable; each can run standalone or as part of the full pipeline.
- **Evaluation harnesses** — Built-in benchmarks (for example, FreshQA, DeepResearch) and evaluation scripts to measure quality and iterate on prompts and agent architecture.
- **Frontend options** — Run through CLI, web UI, or async jobs; the [Getting started](#getting-started) and [Ways to run the agents](#ways-to-run-the-agents).
- **Deployment options** - Deployment assets for a [docker compose](deploy/compose/) as well as helm deployment.


## Software Components

The following are used by this project:

- [NVIDIA NeMo Agent Toolkit](https://docs.nvidia.com/nemo/agent-toolkit/latest/)
- [NVIDIA nemotron-3-nano-30b-a3b](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b/modelcard) (agents)
- [NVIDIA nemotron-mini-4b-instruct](https://build.nvidia.com/nvidia/nemotron-mini-4b-instruct/modelcard) (document summary, if used)
- [NIM of nvidia/llama-3_2-nv-embedqa-1b-v2](https://build.nvidia.com/nvidia/llama-3_2-nv-embedqa-1b-v2) (embedding model for llamaindex knowledge layer implementation, if used)
- [NIM of nvidia/nemotron-nano-12b-v2-vl](https://build.nvidia.com/nvidia/nemotron-nano-12b-v2-vl) (vision-language model for llamaindex knowledge layer implementation, if used)
- [Tavily Search API](https://tavily.com/) for web search
- [Serper Search API](https://serper.dev/) for paper search (Google Scholar)

## Target Audience

This project is for:

- **AI researchers and developers**: People building or extending agentic research workflows
- **Enterprise teams**: Organizations needing tool-augmented research with citation-backed research
- **NeMo Agent Toolkit users**: Developers looking to understand advanced multi-agent patterns

## Prerequisites

- Python 3.11–3.13
- [uv](https://github.com/astral-sh/uv) package manager
- NVIDIA API key from [NVIDIA AI](https://build.nvidia.com) (for NIM models)
- Node.js 18+ and npm (optional, for web UI mode)

**Optional requirements:**
- Tavily API key (for web search functionality)
- Serper API key (for academic paper search functionality)

> **Note:** Configure at least one data source (Tavily web search, Serper search tool, or knowledge layer) to enable research functionality.

If these optional API keys are not provided, the agent continues to operate without the corresponding search capabilities. Refer to [Obtain API Keys](#obtain-api-keys) for details.

## Hardware Requirements

Generalized minimum requirements.

**Local Development**
- Typical developer machine for AI-Q workflow (no GPU required)
- Llamaindex (no GPU required)
- Self / Remote Hosted Models

**Self Hosted**
- Typical server for AI-Q workflow (no GPU required)
- [NVIDIA nemotron-3-nano-30b-a3b](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b/modelcard) (agents)
- [NVIDIA nemotron-mini-4b-instruct](https://build.nvidia.com/nvidia/nemotron-mini-4b-instruct/modelcard) (document summary, if used)
- [NIM of nvidia/llama-3_2-nv-embedqa-1b-v2](https://build.nvidia.com/nvidia/llama-3_2-nv-embedqa-1b-v2) (embedding model for llamaindex knowledge layer implementation, if used)
- [NIM of nvidia/nemotron-nano-12b-v2-vl](https://build.nvidia.com/nvidia/nemotron-nano-12b-v2-vl) (vision-language model for llamaindex knowledge layer implementation, if used)
- [NVIDIA RAG Blueprint Requirements](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/support-matrix.md) (if used)

**Remote Hosted**
- Typical server for workflow (no GPU required)
- Provider LLM API keys (if used)
- [NVIDIA RAG Blueprint Requirements](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/support-matrix.md) (if used)

## Architecture

AI-Q uses a LangGraph-based state machine with the following key components:

- **Orchestration node**: Classifies intent (meta vs. research), produces meta responses when needed, and sets depth (shallow vs. deep) in one step
- **Shallow research agent**: Bounded tool-augmented research optimized for speed
- **Deep research agent**: Multi-phase research with planning, iteration, and citation management

Each agent can be run individually or as part of the orchestrated workflow. For detailed architecture documentation, refer to [Architecture](docs/source/architecture/overview.md).

## Getting Started

### Clone the Repository

```bash
git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git && cd aiq
```

### Automated Setup

Run the setup script to initialize the environment:

```bash
./scripts/setup.sh
```

This script:
- Creates a Python virtual environment with uv
- Installs all Python dependencies (core, frontends, benchmarks, data sources)
- Installs UI dependencies (if Node.js is available)

### Manual Installation

For selective installation, install packages individually:

```bash
# Create and activate virtual environment
uv venv --python 3.13 .venv
source .venv/bin/activate

# Install core with development dependencies
uv pip install -e ".[dev]"

# Install frontends (pick what you need)
uv pip install -e ./frontends/cli          # CLI frontend
uv pip install -e ./frontends/debug        # Debug console
uv pip install -e ./frontends/aiq_api      # Unified API (includes debug)

# Install benchmarks (pick what you need)
uv pip install -e ./frontends/benchmarks/deepresearch_bench
uv pip install -e ./frontends/benchmarks/freshqa

# Install data sources (pick what you need)
uv pip install -e ./sources/tavily_web_search
uv pip install -e ./sources/google_scholar_paper_search
uv pip install -e "./sources/knowledge_layer[llamaindex,foundational_rag]"
```

### Obtain API Keys


| API        | Environment Variable | Purpose                   | Required                                                    |
| ---------- | -------------------- | ------------------------- | ----------------------------------------------------------- |
| NVIDIA API | `NVIDIA_API_KEY`     | LLM inference through NIM | Yes                                                         |
| Tavily     | `TAVILY_API_KEY`     | Web search                | No (if not specified, agent continues without web search)   |
| Serper     | `SERPER_API_KEY`     | Academic paper search     | No (if not specified, agent continues without paper search) |


#### Obtain an NVIDIA API Key

1. Sign in to [NVIDIA Build](https://build.nvidia.com/)
2. Click on any model, then select "Deploy" > "Get API Key" > "Generate Key"

#### Obtain a Tavily API Key

1. Sign in to [Tavily](https://tavily.com/)
2. Navigate to your dashboard
3. Generate an API key

#### Obtain a Serper API Key

1. Sign in to [Serper](https://serper.dev/)
2. Generate an API key from your dashboard

### Set Up Environment Variables

Create a `.env` file in `deploy/` directory:

```bash
cp deploy/.env.example deploy/.env
```

Replace your API keys.

> **Note:** If you do not want to use paper search, follow the steps in the [Customization guide](docs/source/customization/tools-and-sources.md#disabling-a-tool) to disable it.

## Ways to Run the Agents

The `frontends/` directory contains different interfaces for interacting with the agents. You can also run agents directly through the NeMo Agent Toolkit CLI.

### Command-line interface (CLI)

The CLI provides an interactive research assistant in your terminal:

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run with the convenience script
./scripts/start_cli.sh

# Verbose logging
./scripts/start_cli.sh --verbose

# Or run directly with the NeMo Agent Toolkit CLI
nat run --config_file configs/config_cli_default.yml
```

The CLI frontend source is in `frontends/cli/`.

### Web UI

For a full web-based experience:

```bash
./scripts/start_e2e.sh
```

This starts:
- Backend API server at `http://localhost:8000`
- Frontend UI at `http://localhost:3000`

The web UI source is in `frontends/ui/`. Refer to [frontends/ui/README.md](frontends/ui/README.md) for more details.

#### Web UI with Docker Compose

You can also run the backend and UI with Docker Compose:

```bash
cd deploy/compose

# No-auth local setup (LlamaIndex default)
docker compose --env-file ../.env -f docker-compose.yaml up -d --build

# To select a different backend config, set BACKEND_CONFIG in deploy/.env, for example:
# BACKEND_CONFIG=/app/configs/config_web_frag.yml
```

For more details, refer to:
- `deploy/compose/README.md`

### Async Deep Research Jobs

Endpoints, SSE streaming, and debug console: refer to [frontends/aiq_api/README.md](frontends/aiq_api/README.md).

### Benchmarks

To run agents in evaluation mode, refer to the [Evaluating the Workflow](#evaluating-the-workflow) section.


## Evaluating the Workflow

The `frontends/benchmarks/` directory contains evaluation pipelines for assessing agent performance.

### Available Benchmarks

| Benchmark | Description | Location |
|-----------|-------------|----------|
| Deep Research Bench | RACE and FACT evaluation for research quality | `frontends/benchmarks/deepresearch_bench/` |
| FreshQA | Factuality evaluation on time-sensitive questions | `frontends/benchmarks/freshqa/` |

### Running Evaluations

First, install the benchmark package:

```bash
uv pip install -e ./frontends/benchmarks/deepresearch_bench
```

Then run the evaluation with one of the available configurations:

```bash
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench.yml
```

For detailed benchmark documentation, refer to:
- [Deep Research Bench README](frontends/benchmarks/deepresearch_bench/README.md)
- [FreshQA README](frontends/benchmarks/freshqa/README.md)

## Development

For development, contribution, and documentation, refer to:

- **[Development and Contributing](docs/source/contributing/index.md)**: Setup, testing, PR workflow, sign-off/DCO
- **[Architecture](docs/source/architecture/overview.md)**: Component details and data flow
- **[Customization](docs/source/customization/index.md)**: Configuration and customization options
- **[Knowledge Layer Setup](sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md)**: RAG backends and document ingestion
- **[Docs index](docs/README.md)**: Full documentation list and component docs
- **[Changelog](docs/source/resources/changelog.md)**: Version history and changes

## License

This project will download and install additional third-party open source software projects. Review the license terms of these open source projects before use, found in [LICENSE-THIRD-PARTY](LICENSE-THIRD-PARTY). 

GOVERNING TERMS: AIQ blueprint software and materials are governed by the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0)