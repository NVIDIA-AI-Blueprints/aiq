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
3. Creates the job metadata, access-control, admission, event, and
   document-summary tables with their indices in `aiq_jobs`.

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

## Artifact Storage

Keep artifact metadata in PostgreSQL and use S3-compatible object storage for artifact
bytes in production. SQL BLOB storage remains the default when the provider is unset.

| Variable | Required | Description |
|----------|----------|-------------|
| `AIQ_ARTIFACT_BLOB_PROVIDER` | No | `sql` by default; set to `s3` for object storage. |
| `AIQ_ARTIFACT_S3_BUCKET` | With S3 | Destination bucket. |
| `AIQ_ARTIFACT_S3_ENDPOINT_URL` | No | Leave unset for AWS S3; set for MinIO, Ceph, R2, or another compatible endpoint. |
| `AIQ_ARTIFACT_S3_REGION` | No | S3 region when required by the provider. |
| `AIQ_ARTIFACT_S3_PREFIX` | No | Object-key prefix; defaults to `artifacts/v1`. |

Configure credentials through workload identity, deployment secrets, or the standard
AWS credential chain. When the provider is `s3`, artifact bytes are stored in the
configured bucket and SQL stores artifact metadata only.

### S3 Security Responsibility

The S3-compatible artifact store is operator-managed infrastructure. AI-Q authorizes
artifact access through its API, but those checks do not protect direct access to the
bucket. AI-Q also does not apply application-level encryption to artifact blob bytes
before uploading them. Production operators are therefore responsible for configuring
the object store to:

- use workload identity, an instance profile, or an IAM role for service accounts
  instead of long-lived static access keys;
- restrict `GetObject`, `PutObject`, and `DeleteObject` to the AI-Q worker role and
  the configured bucket and prefix;
- block public access and deny requests that do not use TLS;
- enable provider-managed encryption at rest, such as Amazon S3 SSE-KMS, using a key
  policy restricted to the AI-Q worker role; and
- enable object-access audit logs and credential-usage monitoring.

For non-AWS S3-compatible services, configure equivalent identity, bucket-policy,
transport-encryption, storage-encryption, and audit controls. Static access keys are
appropriate only for local development services such as MinIO and must not be used for
production artifact storage.

## Scaling

### Horizontal Backend Scaling

The backend is stateless apart from database connections, so it can be horizontally scaled behind a load balancer.

**Docker Compose:** Run multiple backend containers by scaling the service and using a reverse proxy (such as Traefik or NGINX) in front:

```bash
docker compose --env-file ../.env -f docker-compose.yaml up -d --scale aiq-agent=3
```

Note that each scaled instance starts its own embedded Dask scheduler and worker.
The shipped container entrypoint always creates that embedded cluster. A deployment
that uses a shared Dask cluster must provide a custom entrypoint (for example,
starting `/app/deploy/start_web.py` directly), set
`NAT_DASK_SCHEDULER_ADDRESS` for the web process, and deploy the scheduler
separately.

The embedded scheduler, scheduler dashboard, and worker RPC and diagnostics
listeners bind to `127.0.0.1` and are reachable only within the backend's network
namespace (the same pod when sidecars share its network). An external Dask cluster is
operator-managed infrastructure: place it on a private network, restrict scheduler and
worker ports to the required identities with firewall or NetworkPolicy rules, and
configure Dask TLS. Never expose an unauthenticated scheduler or worker to a shared or
untrusted network.

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

### Deep-Research Admission Control

Every asynchronous deep-research submission, including jobs launched from chat,
passes through a database-backed admission gate before Dask enqueue. The gate is
default-on and fails closed when it cannot make a safe database decision. PostgreSQL
deployments serialize decisions across backend replicas with a transaction-scoped
advisory lock; SQLite serializes writers with an immediate transaction.

| Variable | Default | Behavior |
|----------|---------|----------|
| `AIQ_MAX_DEEP_RESEARCH_INPUT_CHARS` | `32768` | Maximum query payload accepted at admission. It may be lowered; higher values are clamped to the hard per-job contract. |
| `AIQ_MAX_ACTIVE_DEEP_RESEARCH_JOBS_PER_PRINCIPAL` | `5` | Maximum active deep-research jobs for one principal. |
| `AIQ_MAX_ACTIVE_DEEP_RESEARCH_JOBS_GLOBAL` | `50` | Deployment-wide active-job ceiling protecting shared Dask capacity. |
| `AIQ_MAX_DEEP_RESEARCH_SUBMISSIONS_PER_MINUTE` | `20` | Accepted deep-research submissions per principal in a rolling 60-second window. |

Missing, non-integer, zero, or negative values use the safe defaults; these controls
cannot be disabled with `0`. A per-principal capacity or rate rejection returns HTTP
`429`; deployment capacity or admission-store unavailability returns `503`. Capacity
and rate responses include `Retry-After`.

With `REQUIRE_AUTH=true`, the quota key is the verified principal's authentication
type and subject. With `REQUIRE_AUTH=false`, caller-supplied owner text is not trusted
as an identity: all callers share one anonymous admission budget. This prevents owner
rotation from bypassing limits, but it is not tenant isolation. Shared or multi-user
deployments must enable authentication as described below.

### Deep-Research Job Budgets and Provider Quotas

`deep_research_agent.resource_limits` applies non-disableable per-job ceilings
to combined query and clarification input, graph execution time, serialized
plans and final reports, aggregate shared-state file count and bytes, query
count and text, serialized research notes, orchestrator todos, and AI-Q
source-tool attempts and concrete batch items. Defaults are also absolute
maximums; deployments may configure lower values but cannot raise them. The
20-query ceiling also caps persisted notes at 20 because each accepted query
can return at most one `ResearchNotes` file. Researchers cannot write
`/shared/**` directly; the parent batch tool validates and persists their
returned notes.

The source-tool call counter is job-local defense in depth. It is created for
one agent run, inherited by that run's concurrent researcher tasks, and reset
when the run ends. It is **not** a distributed requests-per-minute, token,
spend, or daily-account quota across Dask processes, workers, backend replicas,
or other clients using the same provider credentials. It also cannot count
retries performed internally by a provider SDK.

Production operators remain responsible for provider-account and deployment-wide
controls:

- enforce requests-per-minute, tokens-per-minute, daily usage, and spend limits
  in the provider account, an API gateway, or a shared Redis/database limiter;
- use separate least-privilege credentials and quota pools for production,
  development, and unrelated services;
- alert on quota consumption, HTTP 429 responses, provider error rates, and
  anomalous source-call volume; and
- capacity-plan concurrency below provider limits rather than relying on
  retries after throttling.

Do not use the job-local counter as a substitute for a deployment-wide provider
quota. A production deployment needs an operator-owned distributed limiter or
provider-enforced quota in addition to the per-job defense.

## Security

### Authentication Boundary

The default `REQUIRE_AUTH=false` mode is for a single trusted user or trust domain;
it does not isolate jobs, documents, reports, or artifacts between callers. Do not
publish a no-auth deployment on a shared or untrusted network. Multi-user or externally
reachable deployments must follow the [Authentication](./authentication.md) guide or
place AI-Q behind a customer-managed authenticated gateway with authorization, network
isolation, and edge request limits.

### Non-Root Execution

The Docker image runs as a non-root user (`aiq`, UID 1000) in both dev and release targets. The NVIDIA distroless base image has no shell and no package manager, reducing the attack surface.

### Read-Only Configuration Mounts

The compose stack mounts `configs/` as read-only (`:ro`), preventing the application from modifying its own configuration at runtime.

### Secrets Management

Store API keys in `deploy/.env` and ensure the file is not committed to version control (it is listed in `.gitignore`). Never embed keys in configuration files or Dockerfiles.

### Sandbox Runtime Ownership

Treat optional sandbox runtimes as separate execution and authentication boundaries.
Production OpenShell requires an explicitly owned authenticated gateway, a distinct
policy-bound sandbox per job, verified terminal cleanup, and hard Landlock enforcement.
Follow the [Linux production acceptance](./openshell.md#linux-production-acceptance)
and [policy/config pairing](./openshell.md#policy-and-ai-q-config-pairing) contracts;
do not infer production readiness from a macOS best-effort demo.

## Monitoring

### Liveness and Readiness Endpoints

The backend exposes separate probe endpoints:

- `/live` checks only that the API process can respond. Use it for liveness probes.
- `/health` checks database and content-encryption dependencies. Use it for readiness probes.

This separation keeps a temporary dependency outage from restarting a live API process while still removing an
unready instance from service traffic.

```bash
curl http://localhost:8000/live
curl http://localhost:8000/health
```

### Log Tailing

Backend logs show agent execution, tool calls, LLM interactions, and job lifecycle events.

```bash
docker logs aiq-agent -f
```

Set `LOG_LEVEL=DEBUG` for verbose output during troubleshooting. Use `LOG_LEVEL=WARNING` in production to reduce log volume.

### Tracing

The backend supports OpenTelemetry-compatible tracing. See [Observability](./observability.md) for setup guides covering Phoenix, LangSmith, Weave, and the OTEL Collector with privacy redaction.

If you are deploying the `aiq_api` front-end and want request correlation on
NAT-exported spans, set the relevant environment variables at deploy time rather
than hardcoding them in code:

- `AIQ_TRACE_USER_IDENTITY_MODE`
- `AIQ_TRACE_USER_IDENTITY_HMAC_SECRET`
- `AIQ_TRACE_CLIENT_ID_MODE`
- `AIQ_TRACE_CLIENT_ID_HMAC_SECRET`
- `AIQ_TRACE_CLIENT_IP_HEADERS`

### Metrics to Watch

| Metric | Source | What to look for |
|--------|--------|------------------|
| Backend response time | Health endpoint, access logs | Increasing latency indicates resource pressure or LLM API slowdowns. |
| Job queue depth | `job_info` table (`status='pending'`) | Growing backlog means Dask workers cannot keep up. |
| Database connections | PostgreSQL `pg_stat_activity` | Connection exhaustion from too many backend replicas. |
| Container restarts | Docker | Frequent restarts indicate OOM kills or startup failures. |
| Dask worker memory | Exported Dask metrics, or the loopback-only dashboard inspected from inside the backend container through an approved access path | Memory growth in workers during deep research. Do not publish port 8787 on a shared or untrusted network. |
