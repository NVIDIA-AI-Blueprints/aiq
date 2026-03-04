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

> **⚠️ IMPORTANT – Active Research Branch**
>
> You are currently viewing the **`drb1`** branch for the pre-release version of **AI-Q v2.0**.
> 
> This branch contains features and experimental updates that we are submitting to the Deep Research Bench Leaderboard and may contain breaking changes.
>
> For production use, switch to the **v1.2.1 stable release** on the [`main branch`](https://github.com/NVIDIA-AI-Blueprints/aiq/tree/main).


## Table of Contents
- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [API Keys](#api-keys)
- [Running Evaluation](#running-evaluation)
- [Optional: Phoenix Tracing](#optional-phoenix-tracing)
- [License](#license)

## Overview

NVIDIA AI-Q provides a multi-agent deep research system that produces comprehensive, cited research reports. It uses an orchestrator that delegates to a planner (evidence-grounded planning via web search) and multiple researcher subagents (ensemble web search + academic paper search), then synthesizes findings into a final report. It is built using [NVIDIA NAT](https://github.com/NVIDIA/NeMo-Agent-Toolkit) and the [deepagents](https://github.com/langchain-ai/deepagents) library.

## Prerequisites

- Python 3.11-3.13
- [uv](https://github.com/astral-sh/uv) package manager
- NVIDIA API key from [NVIDIA Build](https://build.nvidia.com/)

Recommended for research quality:
- Tavily API key (web search)
- You.com API key (web search)
- Serper API key (paper search)

## Setup

Clone and set up the environment:

```bash
git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git && cd aiq
git checkout drb1
./scripts/setup.sh
```

Create your environment file:

```bash
cp deploy/.env.example deploy/.env
```

## API Keys

Set the keys in `deploy/.env`:

| API | Environment Variable | Purpose | Required |
| --- | --- | --- | --- |
| NVIDIA Build | `NVIDIA_API_KEY` | Agent LLM inference | Required |
| Gemini | `GEMINI_API_KEY` | Judge LLMs for evaluation configs | Required |
| Tavily | `TAVILY_API_KEY` | Web search backend | Required |
| You.com | `YOU_API_KEY` | You.com deep search backend | Optional |
| Serper | `SERPER_API_KEY` | Academic paper search | Required |
| Jina | `JINA_API_KEY` | FACT evaluator page retrieval | Optional |

### You.com API Key

1. Create/sign in to your You.com developer account.
2. Generate an API key.
3. Add `YOU_API_KEY=<your_key>` to `deploy/.env`.

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

## Running Evaluation

### Step 1: Install the dataset

The dataset files are not included in the repository. We have included a script to retrieve them from the [Deep Research Bench Github Repository](https://github.com/Ayanami0730/deep_research_bench/tree/main) and format them for the NeMo Agent Toolkit evaluator.

To download the dataset files, run the following script:

```bash
python frontends/benchmarks/deepresearch_bench/scripts/download_drb_dataset.py
```

### Step 2: Generate reports using NAT evaluation harness

```bash
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/deepresearch_bench/configs/config_ensemble.yml
```

### Step 3: Convert the output into a compatible format
```bash
python frontends/benchmarks/deepresearch_bench/scripts/export_drb_jsonl.py --input <path to your workflow_output.json> --output <path to the output file you want to create with .jsonl extension>
```

### Step 4: Run evaluation
Follow instructions in the [Deep Research Bench Github Repository](https://github.com/Ayanami0730/deep_research_bench/tree/main) to run evaluation and obtain scores.

## Optional: Phoenix Tracing

If your config enables Phoenix tracing, start the Phoenix server before running `nat eval`.

Start server (separate terminal):

```bash
source .venv/bin/activate
phoenix serve
```

Default UI endpoint: `http://localhost:6006`

For detailed benchmark documentation, refer to:
- [Deep Research Bench README](frontends/benchmarks/deepresearch_bench/README.md)

## License

This project will download and install additional third-party open source software projects. Review the license terms of these open source projects before use, found in [LICENSE-THIRD-PARTY](LICENSE-THIRD-PARTY). 

GOVERNING TERMS: AIQ blueprint software and materials are governed by the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0)
