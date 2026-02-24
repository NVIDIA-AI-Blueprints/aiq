# AI-Q API

Unified API plugin for the AI-Q blueprint: **Knowledge API** (collections, documents) and **Async Job API** (agent-agnostic jobs with SSE streaming).

## Quick Start


### Web Mode - Local Development

```bash
# NeMo Agent toolkit auto-creates:
# - Local Dask cluster
# - SQLite database at .tmp/job_store.db
nat serve --config configs/config_web_frag.yml
```

### Production (PostgreSQL + Dask Cluster)

```bash
export NAT_DASK_SCHEDULER_ADDRESS="tcp://scheduler:8786"
export NAT_JOB_STORE_DB_URL="postgresql://user:pass@host:5432/dbname"
nat serve --config configs/config_web_frag.yml
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  NeMo Agent toolkit layer                       │
│                  (Built-in infrastructure)                      │
│                                                                 │
│   nat.front_ends.fastapi/                                       │
│   ├── job_store.py      # JobStore, JobStatus, JobInfo         │
│   ├── async_job.py      # Dask task patterns                   │
│   └── config.py         # db_url, scheduler_address            │
│                                                                 │
│   Provides: Job tracking, Dask scheduling, SQLite/PostgreSQL   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AI-Q API (extension layer)                   │
│                                                                 │
│   frontends/aiq_api/src/aiq_api/                                │
│   ├── jobs/                                                     │
│   │   ├── runner.py           # run_agent_job (generic)         │
│   │   ├── submit.py           # submit_agent_job                │
│   │   ├── callbacks.py        # SSE event generation            │
│   │   ├── event_store.py      # Persistent event storage       │
│   │   └── connection_manager.py  # SSE connection lifecycle     │
│   ├── routes/                                                  │
│   │   ├── jobs.py             # /v1/jobs/async (submit, stream) │
│   │   ├── collections.py     # /v1/collections (Knowledge API) │
│   │   └── documents.py       # /v1/documents (upload, ingest)   │
│   ├── models/requests.py     # Pydantic request/response models │
│   ├── registry.py            # Agent type registry              │
│   ├── plugin.py              # NAT FastAPI plugin (AIQAPIWorker)│
│   └── websocket_reconnect.py # SSE reconnect handling           │
│                                                                 │
│   Provides: Async jobs + SSE streaming, Knowledge API, event replay │
└─────────────────────────────────────────────────────────────────┘
```

## API Routes

Base path: `/v1/jobs/async`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/jobs/async/agents` | GET | List available agent types |
| `/v1/jobs/async/submit` | POST | Submit a new job |
| `/v1/jobs/async/job/{id}` | GET | Get job status |
| `/v1/jobs/async/job/{id}/stream` | GET | SSE stream from beginning |
| `/v1/jobs/async/job/{id}/stream/{last_event_id}` | GET | SSE stream from event ID |
| `/v1/jobs/async/job/{id}/cancel` | POST | Cancel running job |
| `/v1/jobs/async/job/{id}/state` | GET | Get current UI state |
| `/v1/jobs/async/job/{id}/report` | GET | Get final report |

### List Available Agents

```bash
curl http://localhost:8000/v1/jobs/async/agents
```

Response:

```json
{
  "agents": [
    {"agent_type": "deep_researcher", "description": "Performs comprehensive multi-loop deep research"},
    {"agent_type": "shallow_researcher", "description": "Performs quick single-turn research"}
  ]
}
```

### Submit a Job

```bash
curl -X POST http://localhost:8000/v1/jobs/async/submit \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "deep_researcher", "input": "Research quantum computing trends in 2026"}'
```

Optional body fields: `job_id` (custom ID), `expiry_seconds` (600–604800).

Response:

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "submitted",
  "agent_type": "deep_researcher"
}
```

### Stream Events (SSE)

```bash
curl http://localhost:8000/v1/jobs/async/job/{job_id}/stream
```

#### Replay and Live Handoff

When a client reconnects to an in-progress job stream, the server replays historical events as fast as possible. The server then sends a `stream.mode` event to indicate that catch-up is complete and the stream has switched to live polling.

Expected handoff event:

```
event: stream.mode
data: {"mode":"live"}
```

The `stream.mode` live event is sent once, after historical replay is complete and before subsequent live events.

### Get Final Report

```bash
curl http://localhost:8000/v1/jobs/async/job/{job_id}/report
```

## SSE Event Types

Events streamed during job execution:

| Event | Description |
|-------|-------------|
| `stream.mode` | Stream state transition event. `{"mode":"live"}` signals replay is complete and live streaming has started |
| `job.status` | Job status changes (running, success, failure) |
| `workflow.start` / `workflow.end` | Workflow lifecycle |
| `llm.start` / `llm.chunk` / `llm.end` | LLM inference progress |
| `tool.start` / `tool.end` | Tool invocations |
| `artifact.update` | Todos, files, citations, output updates |
| `job.error` | Error occurred |

## Configuration

### Default Behavior

| Mode | Async Jobs | Database | Notes |
|------|------------|----------|-------|
| **CLI** (`nat run`) | No | None | Agents run via WebSocket |
| **Web** (`nat serve`) | Yes | `./jobs.db` (or `front_end.db_url`) | Auto-creates Dask + SQLite |
| **Production** | Yes | PostgreSQL | Set `NAT_JOB_STORE_DB_URL` or `front_end.db_url` |

### NAT Config File

```yaml
# configs/config_web_frag.yml
general:
  front_end:
    _type: aiq_api
    runner_class: aiq_api.plugin.AIQAPIWorker
    db_url: sqlite+aiosqlite:///./jobs.db   # Job store + event store
    expiry_seconds: 86400

functions:
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_llm
    tools: [tavily_web_search]
```

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `NAT_DASK_SCHEDULER_ADDRESS` | Dask scheduler | Auto-created local |
| `NAT_JOB_STORE_DB_URL` | Job store + event store database | `sqlite+aiosqlite:///./jobs.db` (or via front_end.db_url) |


## Registering New Agents

Agents are registered by type so the job runner can load them from NAT config. Register at import time (e.g. in your NAT plugin or app startup):

```python
from aiq_api.registry import register_agent

register_agent(
    agent_type="my_agent",
    class_path="my_package.agent.MyAgent",
    config_name="my_agent_config",
    description="My custom agent",
)
```

Requirements:
- **config_name** must match a NAT function in your YAML (e.g. `deep_research_agent`).
- The agent class must be constructable from that config and support the run signature expected by the runner (see `jobs/runner.py`).

## Knowledge API

When a `knowledge_retrieval` function is configured in your workflow, the plugin adds:

- **`/v1/collections`** – Create and list collections (uses the same ingestor as the knowledge tool).
- **`/v1/documents`** – Upload files and trigger ingestion.

Backend (LlamaIndex, Foundational RAG, etc.) is determined by the `knowledge_retrieval` config. If no knowledge function is configured, these routes are not registered.

## Debug Console

When the `aiq_debug` package is installed, the plugin registers a debug console at **`http://localhost:8000/debug`**:

- Real-time SSE streaming
- Job submission and tracking
- State visualization (todos, subagents, sources, tool calls)
- Copy SSE streams for debugging

## Comparison with NAT's Built-in Async

| Feature | NAT `/generate/async` | `/v1/jobs/async` |
|---------|----------------------|------------|
| Job tracking | JobStore | Same JobStore |
| Dask scheduling | Yes | Yes |
| Database | SQLite/Postgres | Same |
| **Agent-agnostic** | No | Yes |
| **SSE streaming** | No | Real-time events |
| **Event replay** | No | Via `last_event_id` |

## Related Documentation

- [Project ARCHITECTURE](../../docs/source/architecture/overview.md) – Overall system architecture
