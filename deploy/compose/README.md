# NVIDIA AI-Q Blueprint - Docker Compose

Use this guide to deploy the AI-Q blueprint with Docker Compose. The deployment
starts a FastAPI backend, PostgreSQL for async jobs and checkpoints, and an embedded Dask scheduler and worker for background work.

## Prerequisites

Make sure you have the following before you start:
- Docker Engine and Docker Compose v2.
- API keys for the models and tools you plan to use.
- Ports `3000`, `8000`, and `5432` available on your host.
- Enough disk space for Docker volumes and cached model artifacts.

## Files and Directories

The Docker Compose setup uses these files and folders:
- `deploy/compose/docker-compose.yaml` for the Docker Compose stack.
- `deploy/.env` for environment variables.
- `configs/config_web_default_llamaindex.yml` for the web workflow configuration (default).
- `configs/config_web_frag.yml` for the web workflow configuration (Foundational RAG).
- `configs/config_cli_default.yml` for the CLI workflow configuration (default).
- `deploy/compose/init-db.sql` for PostgreSQL initialization.

## Configure Environment Variables

Follow these steps to prepare your environment:
1. Copy the example environment file: `cp deploy/.env.example deploy/.env`.
2. Update `deploy/.env` with API keys and database settings.

### Backend Configuration

Set `BACKEND_CONFIG` in `deploy/.env` to select the backend workflow config:

- LlamaIndex (default): `/app/configs/config_web_default_llamaindex.yml`
- Foundational RAG (FRAG): `/app/configs/config_web_frag.yml`

### Required API Keys

Set the following keys in `deploy/.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `NVIDIA_API_KEY` | Yes | NVIDIA API key for NIM access when using NVIDIA-hosted models. |
| `TAVILY_API_KEY` | One required | Web search provider key. |
| `SERPER_API_KEY` | One required | Web search provider key (alternative to Tavily). |

### Optional API Keys

Set these keys only if the configuration enables the related features:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | No | Required only if your config uses OpenAI models. |
| `JINA_API_KEY` | No | Required only if you enable the evaluation suite. |
| `WANDB_API_KEY` | No | Required only if you enable experiment tracking. |

### Database Settings

Choose one database configuration in `deploy/.env`:

**PostgreSQL (recommended):**
- Set `NAT_JOB_STORE_DB_URL` to
  `postgresql+asyncpg://aiq:aiq_dev@postgres:5432/aiq_jobs`.
- Set `AIQ_CHECKPOINT_DB` to
  `postgresql://aiq:aiq_dev@postgres:5432/aiq_checkpoints`.
- Set `AIQ_SUMMARY_DB` to
  `postgresql+psycopg://aiq:aiq_dev@postgres:5432/aiq_jobs`.

**SQLite (dev environment):**
- Set `NAT_JOB_STORE_DB_URL` to
  `sqlite+aiosqlite:///./data/jobs.db`.
- Set `AIQ_CHECKPOINT_DB` to
  `/app/data/checkpoints.db`.
- Leave `AIQ_SUMMARY_DB` unset (defaults to `sqlite+aiosqlite:///./summaries.db`).
- You can keep the `postgres` service running or remove the `depends_on` block
  for `aiq-agent` if you want a SQLite-only setup.

## Start Services

### Option 1: Build locally (default)

Run the following commands from the repository root:

```bash
cd deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml up -d --build
```

### Option 2: Use pre-built images from registry

To use pre-built images instead of building locally, set the `BACKEND_IMAGE` and `FRONTEND_IMAGE` environment variables and omit the `--build` flag:

```bash
cd deploy/compose

# Login to the container registry first
docker login nvcr.io

# Run with pre-built images
BACKEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-agent:2603.7.rc0 \
FRONTEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-frontend-v2:2603.7.rc0 \
docker compose --env-file ../.env -f docker-compose.yaml up -d
```

You can also add these to your `deploy/.env` file:

```bash
BACKEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-agent:2603.7.rc0
FRONTEND_IMAGE=nvcr.io/nvstaging/blueprint/aiq-frontend-v2:2603.7.rc0
```

Then run without specifying them on the command line:

```bash
docker compose --env-file ../.env -f docker-compose.yaml up -d
```

Services started:
- `aiq-agent` (port 8000)
- `aiq-blueprint-ui` (port 3000)
- `postgres` (port 5432)

## Foundational RAG (FRAG) prerequisites

If you switch the backend to `configs/config_web_frag.yml`, you must run a compatible RAG server and ingest server separately and set:

- `RAG_SERVER_URL`
- `RAG_INGEST_URL`

Use the NVIDIA RAG Blueprint Docker guides to deploy those services:

- [Get Started With the NVIDIA RAG Blueprint (self-hosted)](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-self-hosted.md)
- [Deploy NVIDIA RAG Blueprint with Docker (NVIDIA-hosted models)](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-nvidia-hosted.md)

### Networking when AI-Q and RAG run as separate compose stacks

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

### Frontend runtime variables

The compose files are designed so the frontend only needs two runtime variables:

- `REQUIRE_AUTH`: Set to `true` to require OAuth login, or `false` (default) for anonymous access.
- `BACKEND_URL`: Backend API URL for the UI container (default uses the backend service name).

Set these variables in `deploy/.env` and use `--env-file ../.env` when you run `docker compose`.

### Release Build

```bash
cd deploy/compose
BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml up -d --build
```

## Stop Services

```bash
cd deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml down
# OR stop and remove volumes
docker compose --env-file ../.env -f docker-compose.yaml down -v
```

## Port Configuration

You can customize the host ports if the defaults conflict with other services:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | Backend API host port |
| `FRONTEND_PORT` | 3000 | Frontend UI host port |

Set these variables in `deploy/.env` or pass them on the command line:

```bash
PORT=8100 docker compose --env-file ../.env -f docker-compose.yaml up -d
```

**Note**: The backend API always runs on port 8000 inside the container. The `PORT` variable only changes the host port mapping.

Common conflicts:
- RAG Blueprint `page-elements` service uses ports 8000-8002. Set `PORT=8100` to avoid this conflict.
- Other development servers may use common ports like 8000, 8080, or 3000.

## Troubleshooting

**Check logs:**
```bash
docker logs aiq-agent -f
docker logs aiq-blueprint-ui -f
docker logs aiq-postgres -f
```

**Health check:**
```bash
curl http://localhost:8000/health
```

**Database connection:**
```bash
docker exec -it aiq-postgres psql -U aiq -d aiq_jobs
```

**Rebuild:**
```bash
cd deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml down
docker compose --env-file ../.env -f docker-compose.yaml build --no-cache
docker compose --env-file ../.env -f docker-compose.yaml up -d
```

## Custom Startup Script

The container uses `start_web.py` instead of `nat serve` to avoid asyncio event loop conflicts between the
NeMo Agent toolkit runtime and FastAPI/Starlette anyio event loop management. See [start_web.py](../start_web.py)
for details.

## Security

- Non-root user (`aiq`, UID 1000)
- Read-only config mounts

## Next Steps

- [Main README](../../README.md)
- [Development and Contributing Guide](../../CONTRIBUTING.md)
