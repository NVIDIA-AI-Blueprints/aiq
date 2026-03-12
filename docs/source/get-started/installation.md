<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Installation

This guide walks through setting up the AI-Q blueprint for local development. For containerized or production deployments, refer to [Deployment](../deployment/index.md).

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11 -- 3.13 | 3.13 recommended |
| [uv](https://github.com/astral-sh/uv) | latest | Python package manager (installed automatically by the setup script if missing) |
| Git | 2.x+ | |
| Node.js | 22+ | Optional -- only needed for the web UI |

You also need at least one LLM API key. Refer to [API key setup](#api-key-setup) below.

### Hardware Requirements

When using [NVIDIA API Catalog](https://build.nvidia.com/) (the default), inference runs on NVIDIA-hosted infrastructure and there are no local GPU requirements. The hardware requirements below apply only when self-hosting models via [NVIDIA NIM](https://docs.nvidia.com/nim/).

| Component | Default Model | Self-Hosted Hardware Reference |
|-----------|---------------|-------------------------------|
| LLM (intent classifier, orchestrator, planner) | `nvidia/nemotron-3-nano-30b-a3b` | [Nemotron 3 Nano support matrix](https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html#nvidia-nemotron-3-nano) |
| LLM (deep research researcher) | `nvidia/nemotron-3-super-120b-a12b` | [Nemotron 3 Super support matrix](https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html#nvidia-nemotron-3-super) |
| LLM (deep research orchestrator/planner, optional) | `openai/gpt-oss-120b` | [GPT OSS support matrix](https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html#gpt-oss-120b) |
| Document summary (optional) | `nvidia/nemotron-mini-4b-instruct` | [Nemotron Mini 4B](https://build.nvidia.com/nvidia/nemotron-mini-4b-instruct/) |
| Text embedding | `nvidia/llama-nemotron-embed-vl-1b-v2` | [NeMo Retriever embedding support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-embedding/latest/support-matrix.html) |
| VLM (image/chart extraction, optional) | `nvidia/nemotron-nano-12b-v2-vl` | [Vision language model support matrix](https://docs.nvidia.com/nim/vision-language-models/latest/support-matrix.html#nemotron-nano-12b-v2-vl) |
| Knowledge layer (Foundational RAG, optional) | -- | [RAG Blueprint support matrix](https://docs.nvidia.com/rag/latest/support-matrix.html) |

## Automated Setup (Recommended)

The setup script handles everything -- virtual environment, Python dependencies, and UI dependencies:

```bash
git clone <repository-url>
cd aiq

./scripts/setup.sh
```

The script performs the following steps:

1. Installs `uv` if not already present
2. Creates a Python 3.13 virtual environment at `.venv/`
3. Installs the core package with dev dependencies
4. Installs all frontends (CLI, debug console, API server)
5. Installs benchmark packages (freshqa, deepsearch_qa)
6. Installs all data source plugins (Tavily, Google Scholar, knowledge layer)
7. Sets up pre-commit hooks
8. Copies `deploy/.env.example` to `deploy/.env` if no `.env` file exists
9. Installs UI npm dependencies (if Node.js is available)

After the script completes, activate the virtual environment:

```bash
source .venv/bin/activate
```

## Manual Setup

If you prefer to install components selectively, follow these steps.

### 1. Clone the Repository

```bash
git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git
cd aiq
```

### 2. Create the Virtual Environment

```bash
uv venv --python 3.13 .venv
source .venv/bin/activate
```

### 3. Install Dependencies

Install the core package and only the frontends, benchmarks, and data sources you need:

```bash
# Core with development dependencies
uv pip install -e ".[dev]"

# Frontends (pick what you need)
uv pip install -e ./frontends/cli          # CLI interface
uv pip install -e ./frontends/debug        # Debug console
uv pip install -e ./frontends/aiq_api      # Unified API server (includes debug)

# Data sources (pick what you need)
uv pip install -e ./sources/tavily_web_search
uv pip install -e ./sources/google_scholar_paper_search
uv pip install -e "./sources/knowledge_layer[llamaindex,foundational_rag]"

# Benchmarks (optional)
uv pip install -e ./frontends/benchmarks/freshqa
uv pip install -e ./frontends/benchmarks/deepsearch_qa
```

### 4. Set Up Pre-Commit Hooks (Development)

```bash
pre-commit install
```

## API Key Setup

AI-Q needs API keys to access LLMs and search providers. Create an environment file from the provided template:

```bash
cp deploy/.env.example deploy/.env
```

Then edit `deploy/.env` and fill in your keys.

### Required Keys

| Variable | Provider | How to obtain |
|----------|----------|---------------|
| `NVIDIA_API_KEY` | [NVIDIA Build](https://build.nvidia.com/) | Sign in, click any model, select Deploy > Get API Key > Generate Key |

### Optional Keys

| Variable | Provider | Purpose |
|----------|----------|---------|
| `TAVILY_API_KEY` | [Tavily](https://tavily.com/) | Web search |
| `SERPER_API_KEY` | [Serper](https://serper.dev/) | Academic paper search (Google Scholar). To enable, uncomment `paper_search_tool` in your config file |

At minimum, you need `NVIDIA_API_KEY` for LLM inference and `TAVILY_API_KEY` for web search. Paper search (`SERPER_API_KEY`) is disabled by default in the shipped configs -- refer to the comments in your config file to enable it.

## Verify Installation

Confirm that the NeMo Agent Toolkit CLI is available and can find the project plugins:

```bash
# Must use the project venv, not the system nat
.venv/bin/nat --help
```

You should observe the `nat` CLI help output with available commands (`run`, `serve`, `eval`, etc.).

To verify plugins are registered:

```bash
.venv/bin/nat run --help
```

This should list available workflow configurations.

## Building the Documentation

The project documentation is built with [Sphinx](https://www.sphinx-doc.org/) and uses MyST-Parser for Markdown support. To build the HTML docs locally:

```bash
# Install docs dependencies and build in one step
uv run --extra docs sphinx-build -M html docs/source docs/build
```

The generated site is written to `docs/build/html/`. Open `docs/build/html/index.html` in a browser to view it.

If you already have the virtual environment activated with docs extras installed, you can also run:

```bash
sphinx-build -M html docs/source docs/build
```

## Next Steps

- **[Quick Start](./quick-start.md)** -- Run your first research query in 5 minutes
- **[Developer Guide](./developer-guide.md)** -- Recommended reading path through the documentation
- **[Deployment](../deployment/index.md)** -- Docker Compose deployment
