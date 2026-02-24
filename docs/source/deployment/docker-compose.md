<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Docker Compose

Docker Compose is the recommended way to run the full AI-Q blueprint stack (backend, frontend, and database) without managing individual processes.

## Prerequisites

- Docker Engine and Docker Compose v2.
- API keys for the models and tools you plan to use (refer to [Installation -- API Key Setup](../get-started/installation.md#api-key-setup)).
- Ports `3000`, `8000`, and `5432` available on your host.
- Enough disk space for Docker volumes and cached model artifacts.

## Files and Directories

The Docker Compose setup uses these files:

| File | Purpose |
|------|---------|
| `deploy/compose/docker-compose.yaml` | Standard stack (LlamaIndex or FRAG backend) |
| `deploy/.env` | Environment variables for all services |
| `deploy/.env.example` | Template with all available variables |
| `deploy/compose/init-db.sql` | PostgreSQL initialization script |
| `configs/config_web_default_llamaindex.yml` | LlamaIndex backend config (default) |
| `configs/config_web_frag.yml` | Foundational RAG backend config |

## Environment Setup

Copy the example environment file and edit it:

```bash
cp deploy/.env.example deploy/.env
```

The sections below explain each group of variables.

### API keys (required)

| Variable | Required | Description |
|----------|----------|-------------|
| `NVIDIA_API_KEY` | Yes | NVIDIA API key for NIM model access. |
| `TAVILY_API_KEY` | Yes | Web search provider key. |
| `SERPER_API_KEY` | No | Google Scholar paper search key (optional). |

### API keys (optional)

| Variable | Description |
|----------|-------------|
| `INFERENCE_NVIDIA_API_KEY` | Required when configs reference `inference-api.nvidia.com`. |
| `OPENAI_API_KEY` | Required only if your config uses OpenAI models directly. |
| `JINA_API_KEY` | Required only if you enable the evaluation suite. |
| `WANDB_API_KEY` | Required only if you enable experiment tracking. |

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `production` | Application environment (`development` or `production`). The compose files default to `production`; `deploy/.env.example` sets `development`. |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

### Backend Configuration

Set `BACKEND_CONFIG` to select which workflow config the backend loads at startup. The compose stacks mount `configs/` into the container at `/app/configs`.

| Config path | Description |
|-------------|-------------|
| `/app/configs/config_web_default_llamaindex.yml` | Default -- LlamaIndex backend (no external RAG required). |
| `/app/configs/config_web_frag.yml` | Foundational RAG mode (requires a running RAG Blueprint). |

Example in `deploy/.env`:

```bash
BACKEND_CONFIG=/app/configs/config_web_default_llamaindex.yml
```

### Database Settings

Choose one of the following database configurations.

**PostgreSQL (recommended for all deployments):**

```bash
NAT_JOB_STORE_DB_URL=postgresql+asyncpg://aiq:aiq_dev@postgres:5432/aiq_jobs  # pragma: allowlist secret
AIQ_CHECKPOINT_DB=postgresql://aiq:aiq_dev@postgres:5432/aiq_checkpoints  # pragma: allowlist secret
AIQ_SUMMARY_DB=postgresql+psycopg://aiq:aiq_dev@postgres:5432/aiq_jobs  # pragma: allowlist secret
```

These are the default values used by the compose stack when the variables are unset.

**SQLite (development only):**

```bash
NAT_JOB_STORE_DB_URL=sqlite+aiosqlite:///./data/jobs.db
AIQ_CHECKPOINT_DB=/app/data/checkpoints.db
# AIQ_SUMMARY_DB defaults to sqlite+aiosqlite:///./summaries.db
```

When using SQLite, you can optionally remove the `depends_on` block for the `aiq-agent` service since the `postgres` container is no longer needed.

### Frontend Runtime Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `backend_url` | `http://aiq-agent:8000` | Backend API URL as seen from the frontend container. |

### Dask Worker Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DASK_NWORKERS` | `1` | Number of Dask workers for background job processing. |
| `DASK_NTHREADS` | `4` | Number of threads per Dask worker. |
| `DASK_DISTRIBUTED__LOGGING__DISTRIBUTED` | `warning` | Dask log level (reduce noise). |

## Standard Stack

### Build and Run Locally

From the repository root:

```bash
cd deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml up -d --build
```

This starts three services:

| Service | Container name | Port | Description |
|---------|---------------|------|-------------|
| `aiq-agent` | `aiq-agent` | 8000 | Backend API server with embedded Dask cluster |
| `frontend` | `aiq-blueprint-ui` | 3000 | [Next.js](https://nextjs.org/) web UI |
| `postgres` | `aiq-postgres` | 5432 | PostgreSQL database |

Open [http://localhost:3000](http://localhost:3000) to access the web UI.

### Use Pre-Built NGC Images

To skip the local build and pull pre-built images from the NGC container registry:

```bash
# Log in to the container registry
docker login nvcr.io

# Run with pre-built images (no --build flag)
cd deploy/compose
BACKEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-agent:2603.7.rc0 \
FRONTEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-frontend-v2:2603.7.rc0 \
docker compose --env-file ../.env -f docker-compose.yaml up -d
```

You can also add the image variables to `deploy/.env` instead of passing them on the command line:

```bash
BACKEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-agent:2603.7.rc0
FRONTEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-frontend-v2:2603.7.rc0
```

### Release Build

To build the production (release) image instead of the development image:

```bash
cd deploy/compose
BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml up -d --build
```

The release image excludes the CLI and debug UI. Refer to [Docker Build System](./docker-build.md) for details on build targets.

## Port Configuration

If the default ports conflict with other services, override them in `deploy/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Backend API host port |
| `FRONTEND_PORT` | `3000` | Frontend UI host port |

```bash
PORT=8100 docker compose --env-file ../.env -f docker-compose.yaml up -d
```

**Note:** The backend API always runs on port 8000 inside the container. The `PORT` variable only changes the host port mapping.

Common conflicts:
- The NVIDIA RAG Blueprint `page-elements` service uses ports 8000--8002. Set `PORT=8100` to avoid this.
- Other development servers may occupy ports 8000, 8080, or 3000.

## Foundational RAG (FRAG) Integration

If you switch the backend to `configs/config_web_frag.yml`, you must run a compatible RAG server and ingest server separately and set these variables in `deploy/.env`:

```bash
RAG_SERVER_URL=http://rag-server:8081/v1
RAG_INGEST_URL=http://ingestor-server:8082/v1
```

Deploy the RAG services using the NVIDIA RAG Blueprint Docker guides:

- [Get Started With the NVIDIA RAG Blueprint (self-hosted)](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-self-hosted.md)
- [Deploy NVIDIA RAG Blueprint with Docker (NVIDIA-hosted models)](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-nvidia-hosted.md)

### Cross-Stack Networking

When AI-Q and RAG are deployed as separate Docker Compose stacks, the AI-Q backend cannot resolve RAG service names (`rag-server`, `ingestor-server`) because the containers are on different Docker networks.

Connect the AI-Q backend container to the RAG network after both stacks are running:

```bash
docker network connect nvidia-rag aiq-agent
```

Then use the RAG service names directly in `deploy/.env`:

```bash
RAG_SERVER_URL=http://rag-server:8081/v1
RAG_INGEST_URL=http://ingestor-server:8082/v1
```

This must be re-run if the `aiq-agent` container is recreated (for example, after `docker compose down && up`).

## Database Setup

### PostgreSQL (default)

The compose stack includes a PostgreSQL 16 container (`postgres:16-alpine`). On first startup with a fresh volume, the `init-db.sql` script runs automatically and:

1. Creates the `aiq_checkpoints` database (the `aiq_jobs` database is created by the `POSTGRES_DB` environment variable).
2. Grants permissions to the `aiq` user.
3. Creates the `job_info` table in `aiq_jobs` with performance indices.

Tables created automatically by the application at runtime:
- `job_events` -- created by `event_store.py` using SQLAlchemy.
- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) checkpoint tables -- created by `AsyncPostgresSaver`.
- `summaries` -- created by `summary_store.py` if not present.

The PostgreSQL healthcheck verifies both `aiq_jobs` and `aiq_checkpoints` databases are ready before the backend starts.

### SQLite Alternative

For lightweight development without PostgreSQL, configure SQLite connection strings in `deploy/.env` (refer to [Database Settings](#database-settings) above). No `init-db.sql` is needed -- the application creates SQLite files on demand.

## Volume Mounts

| Volume | Mount point | Purpose |
|--------|-------------|---------|
| `../../configs` (bind mount, read-only) | `/app/configs` | Workflow configuration files |
| `aiq-data` (named volume) | `/app/data` | LlamaIndex persistence (ChromaDB), SQLite databases |
| `postgres-data` (named volume) | `/var/lib/postgresql/data` | PostgreSQL data directory |

## Stopping and Cleanup

```bash
cd deploy/compose

# Stop containers (preserves data volumes)
docker compose --env-file ../.env -f docker-compose.yaml down

# Stop and remove volumes (deletes all database data)
docker compose --env-file ../.env -f docker-compose.yaml down -v
```

## Troubleshooting

### Check Container Logs

```bash
docker logs aiq-agent -f
docker logs aiq-blueprint-ui -f
docker logs aiq-postgres -f
```

### Verify the Backend Is Healthy

```bash
curl http://localhost:8000/health
```

### Connect to the Database

```bash
docker exec -it aiq-postgres psql -U aiq -d aiq_jobs
```

### Rebuild Without Cache

If containers fail to start or you suspect stale build layers:

```bash
cd deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml down
docker compose --env-file ../.env -f docker-compose.yaml build --no-cache
docker compose --env-file ../.env -f docker-compose.yaml up -d
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Backend fails to start | Missing API keys in `deploy/.env` | Verify `NVIDIA_API_KEY` and at least one search key are set. |
| Frontend shows connection error | Backend not yet ready | Wait for the backend healthcheck to pass; check `docker logs aiq-agent`. |
| Port already in use | Another service occupies 3000, 8000, or 5432 | Override with `PORT` or `FRONTEND_PORT` variables. |
| Database connection refused | PostgreSQL not healthy | Check `docker logs aiq-postgres`; verify `init-db.sql` ran correctly. |
| FRAG mode fails to connect to RAG | Separate Docker networks | Run `docker network connect nvidia-rag aiq-agent`. |
