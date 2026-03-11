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

## VM / Remote Development

If you are running the AI-Q blueprint on a remote VM (cloud instance, WSL, SSH server) and accessing it from your local browser, `localhost:3000` and `localhost:8000` will not resolve because the services are listening on the VM — not your local machine.

### SSH Port Forwarding

Forward the required ports through your SSH connection:

```bash
# Forward both the frontend and backend ports
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@your-vm-host
```

Then open [http://localhost:3000](http://localhost:3000) on your local machine as usual.

To forward ports to an already-active SSH session, you can also use `~C` (SSH escape sequence) to open the SSH command line and type the following on a single line (press Enter at the end):

```text
-L 3000:localhost:3000 -L 8000:localhost:8000
```

### VS Code Remote SSH

If you are using VS Code Remote-SSH, ports are typically forwarded automatically when the server starts listening. If not, open the **Ports** panel (`Ctrl+Shift+P` → "Ports: Focus on Ports View") and add ports `3000` and `8000` manually.

### Common Symptoms

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| "This site can't be reached" on `localhost:3000` or `localhost:8000` | Ports not forwarded from VM to local machine | Use SSH port forwarding (see above) |
| Connection refused after forwarding | Service not running on the VM | SSH into the VM and verify with `curl http://localhost:8000/health` |
| Port forwarding conflicts | Local port already in use | Use alternate local ports: `ssh -L 3001:localhost:3000 -L 8001:localhost:8000 user@vm` |

```{note}
Docker Compose deployments on the VM handle container-to-host port mapping automatically. The SSH forwarding described here is for making the VM's ports accessible on your local machine.
```

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

For full setup instructions covering Phoenix, LangSmith, and other tracing backends, see [Observability](../deployment/observability.md).

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
