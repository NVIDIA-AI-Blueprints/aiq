<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# REST API

The AI-Q blueprint exposes a REST API built on top of NeMo Agent Toolkit's built-in [FastAPI](https://fastapi.tiangolo.com/) infrastructure. The **AI-Q API** is an extension layer that adds agent-agnostic async job management with SSE streaming, knowledge management endpoints, and event replay capabilities.

The API is served when running in **web mode** (`nat serve`). CLI mode (`nat run`) uses WebSocket communication instead and does not expose these endpoints.

## Architecture

NeMo Agent Toolkit provides the core infrastructure: job tracking, [Dask](https://www.dask.org/) scheduling, and SQLite/PostgreSQL persistence. The AI-Q API plugin (`aiq_api`) extends this with:

- **Async Jobs API** -- submit research queries to any registered agent, track progress through SSE
- **Knowledge API** -- manage document collections and trigger ingestion (when a knowledge function is configured)
- **Event replay** -- reconnect to an in-progress job and replay historical events from any point

## Async Jobs API

Base path: `/v1/jobs/async`

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/jobs/async/agents` | List registered agent types |
| `POST` | `/v1/jobs/async/submit` | Submit a new research job |
| `GET` | `/v1/jobs/async/job/{job_id}` | Get job status |
| `GET` | `/v1/jobs/async/job/{job_id}/stream` | SSE event stream from beginning |
| `GET` | `/v1/jobs/async/job/{job_id}/stream/{last_event_id}` | SSE stream from event ID (reconnection) |
| `POST` | `/v1/jobs/async/job/{job_id}/cancel` | Cancel a running job |
| `GET` | `/v1/jobs/async/job/{job_id}/state` | Get accumulated job artifacts |
| `GET` | `/v1/jobs/async/job/{job_id}/report` | Get final research report |
| `GET` | `/v1/data_sources` | List available data sources |
| `GET` | `/health` | Health check (includes Dask status) |

### List Available Agents

Returns all registered agent types that can be used with the submit endpoint.

```bash
curl http://localhost:8000/v1/jobs/async/agents
```

**Response:**

```json
{
  "agents": [
    {"agent_type": "deep_researcher", "description": "Performs comprehensive multi-loop deep research"},
    {"agent_type": "shallow_researcher", "description": "Performs quick single-turn research"}
  ]
}
```

### Submit a Job

Submit a research query to a registered agent. Returns a job ID for tracking progress through SSE.

```bash
curl -X POST http://localhost:8000/v1/jobs/async/submit \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "deep_researcher",
    "input": "Research quantum computing trends in 2026"
  }'
```

**Request body (`JobSubmitRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_type` | `string` | Yes | Agent identifier (for example, `deep_researcher`, `shallow_researcher`) |
| `input` | `string` | Yes | Research query (min 1 character) |
| `job_id` | `string` | No | Custom job ID. Auto-generated UUID if omitted. Pattern: `[a-zA-Z0-9_-]`, max 64 chars |
| `expiry_seconds` | `integer` | No | Job expiry in seconds. Range: 600--604800 (10 min to 7 days). Default from config |

**Response (`JobStatusResponse`):**

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "SUBMITTED",
  "agent_type": "deep_researcher"
}
```

**Error responses:**

| Status | Reason |
|--------|--------|
| `400` | Unknown agent type or invalid request |
| `503` | Dask scheduler not available |

### Get Job Status

```bash
curl http://localhost:8000/v1/jobs/async/job/{job_id}
```

**Response:**

```json
{
  "job_id": "abc123",
  "status": "RUNNING",
  "agent_type": "deep_researcher",
  "error": null,
  "created_at": "2026-02-12T10:30:00Z"
}
```

Job statuses: `SUBMITTED`, `RUNNING`, `SUCCESS`, `FAILURE`, `INTERRUPTED`.

### Stream Events (SSE)

Stream real-time events from a running or completed job using Server-Sent Events.

```bash
# Stream from beginning
curl -N http://localhost:8000/v1/jobs/async/job/{job_id}/stream

# Reconnect from a specific event ID
curl -N http://localhost:8000/v1/jobs/async/job/{job_id}/stream/{last_event_id}
```

Each SSE message has the format:

```
id: 42
event: llm.chunk
data: {"content": "The latest advances..."}
```

#### Replay and Live Handoff

When a client connects (or reconnects) to a job stream, the server replays all historical events as fast as possible, then sends a `stream.mode` event to signal the transition to live streaming. The exact payload depends on the database backend:

- **SQLite (polling):** First sends `{"mode":"polling","interval_ms":500}`, then `{"mode":"live"}` after replay completes.
- **PostgreSQL (pub-sub):** Sends `{"mode":"pubsub","channel":"job_events_<job_id>"}` after replay completes.

After the transition event, new events are delivered in real time. For PostgreSQL backends, the server uses `LISTEN/NOTIFY` for sub-10ms latency. For SQLite, it polls at 500ms intervals.

### Cancel a Job

```bash
curl -X POST http://localhost:8000/v1/jobs/async/job/{job_id}/cancel
```

**Response:**

```json
{
  "job_id": "abc123",
  "status": "INTERRUPTED",
  "task_cancelled": true
}
```

| Status | Reason |
|--------|--------|
| `400` | Job is not in `RUNNING` state |
| `404` | Job not found |

### Get Job Artifacts

Returns accumulated tool calls, outputs, and source citations from a job.

```bash
curl http://localhost:8000/v1/jobs/async/job/{job_id}/state
```

**Response (`JobStateResponse`):**

```json
{
  "job_id": "abc123",
  "has_state": true,
  "state": null,
  "artifacts": {
    "tools": [
      {
        "id": "tool_123",
        "name": "tavily_web_search",
        "input": {"query": "quantum computing 2026"},
        "output": "...",
        "status": "completed",
        "workflow": "shallow_research_agent"
      }
    ],
    "outputs": [
      {
        "type": "citation_source",
        "content": "https://example.com/article",
        "workflow": "shallow_research_agent"
      }
    ],
    "sources": {
      "found": 12,
      "cited": 8,
      "found_urls": ["https://..."],
      "cited_urls": ["https://..."]
    }
  }
}
```

### Get Final Report

```bash
curl http://localhost:8000/v1/jobs/async/job/{job_id}/report
```

**Response (`JobReportResponse`):**

```json
{
  "job_id": "abc123",
  "has_report": true,
  "report": "# Quantum Computing Trends in 2026\n\n..."
}
```

## SSE Event Types

Events streamed during job execution. Refer to the [Data Flow](../architecture/data-flow.md) page for details on how these events are generated and consumed.

| Event | Description |
|-------|-------------|
| `stream.mode` | Stream state transition. In polling mode (SQLite), the server first sends `{"mode":"polling","interval_ms":500}` then `{"mode":"live"}` after replay. In pub-sub mode (PostgreSQL), the server sends `{"mode":"pubsub","channel":"..."}` after replay |
| `job.status` | Job status changes (`RUNNING`, `SUCCESS`, `FAILURE`, `INTERRUPTED`). May include `error` and `reconnected` fields |
| `job.error` | Error occurred during execution |
| `job.shutdown` | Server is shutting down gracefully |
| `job.heartbeat` | Periodic heartbeat from Dask worker (every 30s); keeps SSE connection alive |
| `job.cancelled` | Job was cancelled by user |
| `job.update` | Retry notification when a chain (LLM call) fails and is retried |
| `job.cancellation_requested` | Cancellation was requested by user |
| `workflow.start` / `workflow.end` | Workflow lifecycle boundaries |
| `llm.start` / `llm.chunk` / `llm.end` | LLM inference progress. `llm.chunk` contains streaming token content |
| `tool.start` / `tool.end` | Tool invocation lifecycle. Includes tool name, input, and output |
| `artifact.update` | Structured updates: todos, files, citations (`citation_source`, `citation_use`), output content |

## Agent Registration

Agents are registered by type so the async job runner can load them dynamically. Registration happens at import time (typically in a NeMo Agent Toolkit plugin module):

```python
from aiq_api.registry import register_agent

register_agent(
    agent_type="my_agent",
    class_path="my_package.agent.MyAgent",
    config_name="my_agent_config",
    description="My custom research agent",
)
```

**Parameters:**

| Parameter | Description |
|-----------|-------------|
| `agent_type` | Short identifier used in submit requests (for example, `deep_researcher`) |
| `class_path` | Full module path to the agent class |
| `config_name` | Must match a function name in the NeMo Agent Toolkit YAML config (for example, `deep_research_agent`) |
| `description` | Human-readable description shown in the agent list |

The default agents (`deep_researcher` and `shallow_researcher`) are registered automatically when the `aiq_api` plugin loads.

## Knowledge API

The Knowledge API endpoints are **conditionally registered** -- they appear only when a `knowledge_retrieval` function is configured in the workflow. The backend (LlamaIndex, Foundational RAG, etc.) is determined by the knowledge config.

### Collection Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/collections` | Create a new collection |
| `GET` | `/v1/collections` | List all collections |
| `GET` | `/v1/collections/{name}` | Get collection details |
| `DELETE` | `/v1/collections/{name}` | Delete a collection and all its contents |
| `GET` | `/v1/knowledge/health` | Check knowledge backend health |

#### Create a Collection

```bash
curl -X POST http://localhost:8000/v1/collections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "research-papers",
    "description": "Collection of ML research papers",
    "metadata": {}
  }'
```

#### List Collections

```bash
curl http://localhost:8000/v1/collections
```

### Document Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/collections/{collection_name}/documents` | Upload and ingest documents (returns job ID) |
| `GET` | `/v1/collections/{collection_name}/documents` | List documents in a collection |
| `DELETE` | `/v1/collections/{collection_name}/documents` | Delete documents by file ID |
| `GET` | `/v1/documents/{job_id}/status` | Get ingestion job status |

#### Upload Documents

Document upload is asynchronous. The endpoint returns a job ID that you poll for ingestion status.

```bash
curl -X POST http://localhost:8000/v1/collections/research-papers/documents \
  -F "files=@paper1.pdf" \
  -F "files=@paper2.pdf"
```

**Response (202 Accepted):**

```json
{
  "job_id": "job_abc123",
  "file_ids": ["file_abc123", "file_def456"],
  "message": "Ingestion job submitted for 2 file(s)"
}
```

#### Delete Documents

```bash
curl -X DELETE http://localhost:8000/v1/collections/research-papers/documents \
  -H "Content-Type: application/json" \
  -d '{"file_ids": ["file_abc123", "file_def456"]}'
```

**Request body (`DeleteFilesRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_ids` | `list[string]` | Yes | List of file IDs to delete |

#### Check Ingestion Status

```bash
curl http://localhost:8000/v1/documents/{job_id}/status
```

### List Data Sources

Returns available data sources based on the configured tools.

```bash
curl http://localhost:8000/v1/data_sources
```

**Response:**

```json
[
  {
    "id": "web_search",
    "name": "Web Search",
    "description": "Search the web for real-time information."
  },
  {
    "id": "knowledge_layer",
    "name": "Knowledge Base",
    "description": "Search uploaded documents and files."
  }
]
```

The `knowledge_layer` entry only appears when a knowledge retrieval function is configured.

### Health Check

```bash
curl http://localhost:8000/health
```

**Response:**

```json
{
  "status": "ok",
  "dask_available": true
}
```

## Configuration

The API is configured through the NeMo Agent Toolkit config file under `general.front_end`:

```yaml
general:
  front_end:
    _type: aiq_api
    runner_class: aiq_api.plugin.AIQAPIWorker
    db_url: ${NAT_JOB_STORE_DB_URL:-sqlite+aiosqlite:///./jobs.db}
    expiry_seconds: 86400  # 24 hours
    cors:
      allow_origin_regex: 'http://localhost(:\d+)?'
      allow_methods: [GET, POST, DELETE, OPTIONS]
      allow_headers: ["*"]
      allow_credentials: true
```

### Mode Comparison

| Mode | Command | Async Jobs | Database | API Available |
|------|---------|------------|----------|---------------|
| CLI | `nat run` | No | None | No |
| Web (local) | `nat serve` | Yes | SQLite (`./jobs.db`) | Yes |
| Production | `nat serve` | Yes | PostgreSQL | Yes |

### Database Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `NAT_JOB_STORE_DB_URL` | Job store + event store database | `sqlite+aiosqlite:///./jobs.db` |
| `NAT_DASK_SCHEDULER_ADDRESS` | Dask scheduler for distributed execution | Auto-created local cluster |

For production deployments, use PostgreSQL for both the job store and LISTEN/NOTIFY-based real-time SSE:

```bash
export NAT_JOB_STORE_DB_URL="postgresql+asyncpg://user:pass@host:5432/aiq_jobs"  # pragma: allowlist secret
export NAT_DASK_SCHEDULER_ADDRESS="tcp://scheduler:8786"
```

## Debug Console

When the `aiq_debug` package is installed, a debug console is available at `http://localhost:8000/debug` with:

- Real-time SSE streaming visualization
- Job submission and tracking
- State visualization (todos, subagents, sources, tool calls)
- Copy SSE streams for debugging
