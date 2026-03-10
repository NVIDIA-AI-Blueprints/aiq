<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deployment

The AI-Q blueprint supports multiple deployment methods. Choose the one that best fits your environment and operational requirements.

| Method | Best For | Prerequisites |
|--------|----------|---------------|
| [Docker Compose](./docker-compose.md) | Local development, team demos, single-node deployments | Docker Engine, Docker Compose v2 |
| [Kubernetes (Helm)](./kubernetes.md) | Multi-node clusters, production | Kubernetes cluster, Helm v3.x |
| Manual (no containers) | Development and debugging | Python 3.11--3.13, system dependencies (refer to [Installation](../get-started/installation.md)) |

## Architecture Overview

All containerized deployments run the same three services:

- **Backend** (`aiq-agent`) -- [FastAPI](https://fastapi.tiangolo.com/) server with an embedded [Dask](https://www.dask.org/) scheduler and worker for background job processing.
- **Frontend** (`aiq-blueprint-ui`) -- [Next.js](https://nextjs.org/) web UI that communicates with the backend API.
- **Database** (`postgres`) -- [PostgreSQL](https://www.postgresql.org/) instance for async job storage, [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) checkpoints, and document summaries.

## Deployment Guides

- **[Docker Compose](./docker-compose.md)** -- Full Docker Compose reference covering environment setup, the standard LlamaIndex stack, Foundational RAG (FRAG) integration, database configuration, and troubleshooting.

- **[Kubernetes (Helm)](./kubernetes.md)** -- Helm chart deployment for Kubernetes clusters, including NGC image pull secrets, configuration switching, FRAG integration, and troubleshooting.

- **[Docker Build System](./docker-build.md)** -- Multi-stage Dockerfile architecture, build targets (dev vs. release), base images, and startup scripts (`entrypoint.py` and `start_web.py`).

- **[Observability](./observability.md)** -- Tracing and monitoring with Phoenix, LangSmith, Weave, and OpenTelemetry.

- **[Production Considerations](./production.md)** -- Guidance on managed databases, horizontal scaling, security hardening, monitoring, and resource requirements.

## Quick Start

For the fastest path to a running stack:

```bash
# 1. Configure environment
cp deploy/.env.example deploy/.env
# Edit deploy/.env with your API keys

# 2. Start services
cd deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml up -d --build
```

Open [http://localhost:3000](http://localhost:3000) to access the web UI.
