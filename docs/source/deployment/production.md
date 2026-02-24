<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Production Considerations

This page covers operational guidance for running the AI-Q blueprint in production environments.

## Database

### Use Managed PostgreSQL

The default compose stack includes a PostgreSQL container, but for production workloads consider a managed database service:

- Amazon RDS for PostgreSQL
- Google Cloud SQL for PostgreSQL
- Azure Database for PostgreSQL

Set the following environment variables to point to your managed database:

| Variable | Driver | Example |
|----------|--------|---------|
| `NAT_JOB_STORE_DB_URL` | `asyncpg` | `postgresql+asyncpg://<user>:<pw>@rds-host:5432/aiq_jobs` |
| `AIQ_CHECKPOINT_DB` | `psycopg2` | `postgresql://<user>:<pw>@rds-host:5432/aiq_checkpoints` |
| `AIQ_SUMMARY_DB` | `psycopg` | `postgresql+psycopg://<user>:<pw>@rds-host:5432/aiq_jobs` |

### Database Initialization

When using a managed database, you must run the initialization SQL manually (or as a migration step) since the `init-db.sql` Docker entrypoint script only executes on a fresh PostgreSQL container volume. The script:

1. Creates the `aiq_checkpoints` database.
2. Grants permissions to the application user.
3. Creates the `job_info` table with performance indices in `aiq_jobs`.

Refer to `deploy/compose/init-db.sql` for the full schema.

### Backup Strategy

Back up the following databases regularly:

- **`aiq_jobs`** -- Contains the `job_info` table (job metadata) and `job_events` table (event stream). This is the critical operational data store.
- **`aiq_checkpoints`** -- Contains [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) agent state checkpoints. These allow resumption of interrupted research workflows.

For managed databases, enable automated daily backups with at least 7 days of retention. For self-managed PostgreSQL, use `pg_dump` on a schedule:

```bash
pg_dump -U aiq -d aiq_jobs > aiq_jobs_$(date +%Y%m%d).sql
pg_dump -U aiq -d aiq_checkpoints > aiq_checkpoints_$(date +%Y%m%d).sql
```

## Scaling

### Horizontal Backend Scaling

The backend is stateless apart from database connections, so it can be horizontally scaled behind a load balancer.

**Docker Compose:** Run multiple backend containers by scaling the service and using a reverse proxy (such as Traefik or NGINX) in front:

```bash
docker compose --env-file ../.env -f docker-compose.yaml up -d --scale aiq-agent=3
```

Note that each scaled instance starts its own embedded Dask scheduler and worker. For a shared Dask cluster, deploy Dask separately and set `NAT_DASK_SCHEDULER_ADDRESS` to point to the external scheduler.

### Dask Workers

Each backend container runs an embedded Dask scheduler with a configurable number of workers and threads:

| Variable | Default | Guidance |
|----------|---------|----------|
| `DASK_NWORKERS` | `1` | Increase for higher job throughput. Each worker consumes memory proportional to the research workflow depth. |
| `DASK_NTHREADS` | `4` | Increase for I/O-bound workloads (web searches, API calls). |

### Resource Requirements

Deep research workflows are memory- and compute-intensive due to multi-phase LLM calls. Recommended minimums:

| Component | CPU | Memory | Notes |
|-----------|-----|--------|-------|
| Backend | 2 cores | 4 GB | Increase for deep research or multiple concurrent users. |
| Frontend | 0.5 cores | 512 MB | Lightweight [Next.js](https://nextjs.org/) server. |
| PostgreSQL | 1 core | 2 GB | Increase for high write throughput. |

## Security

### Non-Root Execution

The Docker image runs as a non-root user (`aiq`, UID 1000) in both dev and release targets. The NVIDIA distroless base image has no shell and no package manager, reducing the attack surface.

### Read-Only Configuration Mounts

The compose stack mounts `configs/` as read-only (`:ro`), preventing the application from modifying its own configuration at runtime.

### Secrets Management

Store API keys in `deploy/.env` and ensure the file is not committed to version control (it is listed in `.gitignore`). Never embed keys in configuration files or Dockerfiles.

## Monitoring

### Health Endpoint

The backend exposes a health endpoint at `/health` for liveness and readiness probes.

```bash
curl http://localhost:8000/health
```

### Log Tailing

Backend logs show agent execution, tool calls, LLM interactions, and job lifecycle events.

```bash
docker logs aiq-agent -f
```

Set `LOG_LEVEL=DEBUG` for verbose output during troubleshooting. Use `LOG_LEVEL=WARNING` in production to reduce log volume.

### Tracing

The backend supports OpenTelemetry-compatible tracing. Configure the following for observability:

- **Phoenix tracing** -- Set up Phoenix for local trace visualization during development and debugging.
- **LangSmith** -- For LLM-specific tracing, evaluation, and optimization. Configure `LANGCHAIN_TRACING_V2=true` and set `LANGCHAIN_API_KEY`.

### Metrics to Watch

| Metric | Source | What to look for |
|--------|--------|------------------|
| Backend response time | Health endpoint, access logs | Increasing latency indicates resource pressure or LLM API slowdowns. |
| Job queue depth | `job_info` table (`status='pending'`) | Growing backlog means Dask workers cannot keep up. |
| Database connections | PostgreSQL `pg_stat_activity` | Connection exhaustion from too many backend replicas. |
| Container restarts | Docker | Frequent restarts indicate OOM kills or startup failures. |
| Dask worker memory | Dask dashboard (port 8787) | Memory growth in workers during deep research. |
