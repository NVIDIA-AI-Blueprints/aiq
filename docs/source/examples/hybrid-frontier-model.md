<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Hybrid Frontier Model

The checked-in `configs/config_frontier_models.yml` profile combines NVIDIA NIM models for intent classification and
shallow research with GPT Sol/Luna for clarification and deep research.

## Shipped Configuration

| Role | Model |
| --- | --- |
| Intent classification and shallow research | `nvidia/nemotron-3.5-lightning-30b-a3b` |
| Clarification, orchestration, and planning | `gpt-5.6-sol` |
| Source routing and research | `gpt-5.6-luna` |
| Report writing | `gpt-5.6-sol` with the writer token budget from the checked-in config |
| Document summaries | `google/gemma-4-31b-it` |

Use the profile as checked in so role assignments, inference parameters, retry limits, and structured-response behavior
stay aligned with the documented configuration. Before deployment, run the complete workflow against the exact provider
endpoints and credentials you intend to use.

```{important}
Other bring-your-own models or modified role assignments are custom profiles outside this documented combination.
OpenAI-compatible transport does not guarantee equivalent tool-calling or structured-output behavior. A custom model
can require provider-specific prompt, hyperparameter, tool-calling, and structured-output tuning and should be treated
as experimental until the complete workflow passes evaluation.
```

## Prerequisites

- `NVIDIA_API_KEY` for NVIDIA NIM models
- `OPENAI_API_KEY` for the GPT Sol/Luna roles
- `TAVILY_API_KEY` for the default web-search tools

Set these values in `deploy/.env`; do not store credentials in the YAML file.

## Run the Profile

Start the web API from the repository root:

```bash
uv run dotenv -f deploy/.env run nat serve \
  --config_file configs/config_frontier_models.yml
```

For Docker Compose, set the following value in `deploy/.env` before starting the stack:

```bash
BACKEND_CONFIG=/app/configs/config_frontier_models.yml
```

Then follow the standard [Docker Compose](../deployment/docker-compose.md) startup procedure.

To create a custom model profile, copy the checked-in configuration, change model references in YAML rather than
Python, and evaluate the resulting workflow. Refer to [Swapping Models](../customization/swapping-models.md) for the
support boundary and role-mapping guidance.
