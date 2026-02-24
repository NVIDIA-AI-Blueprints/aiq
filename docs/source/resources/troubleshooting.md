<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Troubleshooting

Common issues and solutions for the AI-Q blueprint.

## Installation Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: aiq_agent` | Package not installed in editable mode | `uv pip install -e .` |
| `nat` command not found | Using system `nat` instead of venv | Use `.venv/bin/nat` or activate the venv |
| NeMo Agent Toolkit plugins not found | Plugins not installed | `uv pip install -e .` to register entry points |
| Pre-commit hook failures | Missing pre-commit setup | `pre-commit install && pre-commit run --all-files` |
| `ormsgpack` attribute error | Version conflict with [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | `uv pip install "ormsgpack>=1.5.0"` |

## API Key Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `[404] Not found for account` | Invalid or expired NVIDIA API key | Regenerate key at [build.nvidia.com](https://build.nvidia.com) |
| `Gateway timeout (504)` | Model endpoint overloaded or unavailable | Retry, or switch to a different model in config |
| Tavily search returns empty | Invalid `TAVILY_API_KEY` | Verify key at [tavily.com](https://tavily.com) |
| Serper search fails | Missing `SERPER_API_KEY` | Set key or remove `paper_search_tool` from config |

## Runtime Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Agent hangs on deep research | LLM timeout or rate limit | Set `verbose: true` in config to see progress; check LLM API availability and rate limits |
| Shallow research returns generic answers | Insufficient tool calls | Increase `max_tool_iterations` (default: 5) |
| Clarifier keeps asking questions | Too many clarification turns | Reduce `max_turns` or set `enable_plan_approval: false` |
| SSE stream disconnects | Network timeout | Client auto-reconnects using `last_event_id`; refer to [Data Flow](../architecture/data-flow.md) |
| Job status stuck on RUNNING | Dask worker crashed | Check Dask logs; the ghost job reaper will eventually mark it FAILURE |

## Knowledge Layer Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `Unknown backend` | Adapter module not imported | Ensure backend package is installed: `uv pip install -e "sources/knowledge_layer[llamaindex]"` |
| Empty retrieval results | Collection is empty or wrong name | Run ingestion first; verify `collection_name` matches |
| Foundational RAG connection refused | RAG Blueprint not running | Start the RAG Blueprint server; verify `rag_url` and `ingest_url` |
| `milvus-lite` required | Missing dependency | `uv pip install "pymilvus[milvus_lite]"` |

## Docker / Deployment Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Container fails to start | Missing environment variables | Check `deploy/.env` has all required keys |
| Port already in use | Another service on port 3000/8000 | Set `PORT=8100` or `FRONTEND_PORT=3100` in `.env` |
| UI shows "Backend unavailable" | Backend not healthy | `curl http://localhost:8000/health`; check backend container logs |

## Debugging Tips

### Enable Verbose Logging

```yaml
# In your config YAML
workflow:
  _type: chat_deepresearcher_agent
  verbose: true
```

Or through CLI: `./scripts/start_cli.sh --verbose`

### Phoenix Tracing

Start a Phoenix server and enable tracing in config:

```yaml
general:
  telemetry:
    tracing:
      phoenix:
        _type: phoenix
        endpoint: http://localhost:6006/v1/traces
        project: dev
```

Then open [http://localhost:6006](http://localhost:6006) to inspect traces, token usage, and latency.

### Check Registered Components

```bash
# List registered NeMo Agent Toolkit plugins
.venv/bin/nat info components
```
