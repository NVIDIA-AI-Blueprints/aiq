<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Observability

The AI-Q blueprint supports multiple observability backends for tracing agent execution, LLM calls, tool invocations, and token usage. Choose the backend that best fits your workflow. For more details on available backends, refer to the [NVIDIA Agent Toolkit observability documentation](https://docs.nvidia.com/nemo/agent-toolkit/latest/run-workflows/observe/observe.html).

| Backend | Best For | Setup |
|---------|----------|-------|
| [Phoenix](#phoenix) | Local development, trace visualization | Run Phoenix server, add YAML config |
| [LangSmith](#langsmith) | LLM evaluation, prompt optimization, team collaboration | Set environment variables |
| [Weights & Biases Weave](#weights--biases-weave) | Experiment tracking, model monitoring | Set environment variables |
| [OpenTelemetry Collector](#opentelemetry-collector) | Production infrastructure, enterprise redaction | YAML config with OTEL endpoint |
| [Verbose Logging](#verbose-logging) | Quick debugging, no external services | CLI flag or YAML config |

## Phoenix

[Phoenix](https://docs.arize.com/phoenix) provides a local UI for visualizing traces, inspecting LLM calls, and analyzing token usage and latency. It is the recommended backend for local development.

### Setup

1. Install Phoenix:

   ```bash
   uv pip install arize-phoenix
   ```

2. Start the Phoenix server:

   ```bash
   python -m phoenix.server.main serve
   ```

   This launches the Phoenix UI at [http://localhost:6006](http://localhost:6006).

3. Enable Phoenix tracing in your YAML config:

   ```yaml
   general:
     telemetry:
       tracing:
         phoenix:
           _type: phoenix
           endpoint: http://localhost:6006/v1/traces
           project: dev
   ```

   The `project` field groups traces under a named project in the Phoenix UI.

### What You Can Inspect

- **Traces** -- Full agent execution trees showing orchestrator routing, tool calls, and LLM interactions.
- **Token usage** -- Per-call input/output token counts and costs.
- **Latency** -- Time spent in each step of the agent pipeline.
- **Tool calls** -- Arguments passed to and results returned from search tools, RAG retrieval, and other data sources.

## LangSmith

[LangSmith](https://smith.langchain.com/) provides cloud-hosted tracing, evaluation datasets, and prompt optimization for LangChain-based applications. It works automatically through the LangChain integration -- no YAML config changes are needed.

### Setup

1. Create an account at [smith.langchain.com](https://smith.langchain.com/) and generate an API key.

2. Set the following environment variables in `deploy/.env`:

   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=lsv2-...
   LANGCHAIN_PROJECT=aiq-research
   ```

   The `LANGCHAIN_PROJECT` variable groups traces under a named project. If omitted, traces go to the `default` project.

3. Start the application as usual. All LangChain and LangGraph operations are traced automatically. No YAML config changes are required -- the LangChain SDK detects these environment variables at startup.

### What You Can Inspect

- **Trace trees** -- Visualize the full agent execution including orchestrator decisions, tool calls, and LLM interactions.
- **LLM calls** -- Input prompts, output completions, token counts, and latency for every model call.
- **Evaluation** -- Build datasets from traced runs and evaluate agent quality over time.

## Weights & Biases Weave

[Weave](https://wandb.ai/site/weave) provides experiment tracking and trace logging integrated with the Weights & Biases platform. NAT includes Weave support via the `weave` extra (`nvidia-nat[weave]`), which is already installed in this project.

### Setup

1. Create a [Weights & Biases](https://wandb.ai/) account if you do not have one.

2. Set the API key in `deploy/.env`:

   ```bash
   WANDB_API_KEY=your-wandb-api-key
   ```

   Alternatively, authenticate interactively:

   ```bash
   wandb login
   ```

3. Enable Weave tracing in your YAML config:

   ```yaml
   general:
     telemetry:
       tracing:
         weave:
           _type: weave
           project: aiq-research
   ```

### Configuration Reference

The Weave exporter supports PII redaction and custom trace attributes:

```yaml
general:
  telemetry:
    tracing:
      weave:
        _type: weave
        project: aiq-research
        verbose: false
        redact_pii: true
        redact_pii_fields:
          - CREDIT_CARD
          - EMAIL_ADDRESS
          - PHONE_NUMBER
        redact_keys:
          - api_key
          - authorization
        attributes:
          environment: development
          team: research
```

| Field | Description |
|-------|-------------|
| `project` | The W&B project name. |
| `verbose` | Enable verbose logging for the Weave exporter. |
| `redact_pii` | Automatically redact PII from traces using Presidio. |
| `redact_pii_fields` | Custom PII entity types to redact (e.g., `CREDIT_CARD`, `EMAIL_ADDRESS`). Only used when `redact_pii` is `true`. |
| `redact_keys` | Additional keys to redact beyond the defaults (`api_key`, `auth_headers`, `authorization`). |
| `attributes` | Custom attributes to include in all trace spans. |

### What You Can Inspect

- **Trace timelines** -- Agent execution flows with timing breakdowns.
- **Model calls** -- Inputs, outputs, and metadata for each LLM invocation.
- **Experiment comparison** -- Compare traces across different configurations or model versions.

## OpenTelemetry Collector

For production environments, the AI-Q blueprint provides a custom OpenTelemetry exporter (`otelcollector_redaction`) that forwards spans to any OTEL-compatible collector (Jaeger, Grafana Tempo, Datadog, etc.) with built-in privacy redaction.

### Setup

Add the exporter to your YAML config:

```yaml
general:
  telemetry:
    tracing:
      otel:
        _type: otelcollector_redaction
        endpoint: http://your-otel-collector:4318/v1/traces
        project: aiq-research
        resource_attributes:
          deployment.environment: production
          service.version: "1.0.0"
```

### Privacy Redaction

The `otelcollector_redaction` exporter can automatically redact sensitive data from trace spans before they leave the application. This is useful for enterprise environments where LLM inputs and outputs may contain PII or confidential information.

```yaml
general:
  telemetry:
    tracing:
      otel:
        _type: otelcollector_redaction
        endpoint: http://your-otel-collector:4318/v1/traces
        project: aiq-research
        redaction_enabled: true
        redaction_attributes:
          - input.value
          - output.value
          - nat.metadata
        force_redaction: false
        redaction_tag: redacted
```

| Field | Description |
|-------|-------------|
| `endpoint` | The OTEL collector URL to send spans to (e.g., `http://your-otel-collector:4318/v1/traces`). |
| `project` | Logical project name attached to all exported spans. |
| `redaction_enabled` | Enable or disable redaction processing. |
| `redaction_attributes` | Span attributes to redact (defaults to `input.value`, `output.value`, `nat.metadata`). |
| `force_redaction` | Always redact, regardless of header conditions. |
| `redaction_tag` | Tag added to spans when redaction is applied. |
| `redaction_headers` | Request headers checked to determine whether to redact. |
| `resource_attributes` | Custom OTEL resource attributes attached to all spans. |

### Request Tags on NAT Spans

When the `aiq_api` auth middleware is enabled, NAT-exported workflow spans can
include low-cardinality request tags plus optional pseudonymous identity tags.
These tags are propagated across HTTP requests, WebSocket workflows, and async
job execution.

Always-on NAT span tags:

- `nat.aiq.caller.type` -- resolved caller type from auth middleware
- `nat.aiq.auth.transport` -- `bearer`, `cookie`, or `none`
- `nat.aiq.auth.verified` -- whether the request resolved to a verified principal
- `nat.aiq.access.channel` -- inferred request channel or trusted explicit access-channel header

Optional pseudonymous tags:

- `nat.enduser.id`, `nat.aiq.user.id`, `nat.aiq.auth.type` -- controlled by `AIQ_TRACE_USER_IDENTITY_MODE`
- `nat.aiq.user.email`, `nat.aiq.user.name` -- added only in `full` mode
- `nat.aiq.client.id` -- controlled by `AIQ_TRACE_CLIENT_ID_MODE=ip`

Environment variables:

- `AIQ_TRACE_USER_IDENTITY_MODE=none|id|full`
- `AIQ_TRACE_USER_IDENTITY_HMAC_SECRET=<secret>`
- `AIQ_TRACE_CLIENT_ID_MODE=none|ip`
- `AIQ_TRACE_CLIENT_ID_HMAC_SECRET=<secret>`
- `AIQ_TRACE_CLIENT_IP_HEADERS=x-real-ip,x-forwarded-for`

The `id` and `ip` modes emit HMAC-derived pseudonymous identifiers rather than
raw subjects or raw IP addresses.

### Batch Configuration

The exporter supports standard OTEL batch settings:

```yaml
general:
  telemetry:
    tracing:
      otel:
        _type: otelcollector_redaction
        endpoint: http://your-otel-collector:4318/v1/traces
        batch_size: 512
        flush_interval: 5000
        max_queue_size: 2048
        drop_on_overflow: false
        shutdown_timeout: 30000
```

## Monocle

[Monocle](https://github.com/monocle2ai/monocle) is an open-source, OpenTelemetry-based tracer for agentic applications. It instruments the frameworks already in use (LangChain, LangGraph, and others) and records each run end-to-end -- LLM calls, agent steps, and tool and MCP invocations, with their inputs, outputs, timings, and token counts. It is packaged as an **optional** tracing backend and is disabled unless you both install it and enable it -- the default install and default behavior are unchanged.

Each run writes one trace file to `.monocle/` in the working directory; open it in the [Monocle VS Code extension](https://marketplace.visualstudio.com/items?itemName=OkahuAI.monocle-apptrace) to inspect the span timeline and token counts. Connect to [Okahu](https://www.okahu.ai), an agent-observability platform, to analyze traces across runs and run trace-based and agentic evaluations (via the `okahu` exporter).

### Install

Monocle ships as an optional extra, so a default install does not pull the OpenTelemetry stack:

```bash
uv sync --extra monocle
# or, in an existing environment:
pip install 'aiq-agent[monocle]'
```

Enabling Monocle without the extra installed fails fast with an actionable error naming the install command; when Monocle is not enabled, `monocle_apptrace` is never imported.

### Enable

There are two ways to opt in. Both forward the exporter list to `setup_monocle_telemetry(workflow_name="nvidia-aiq", monocle_exporters_list=...)` and Monocle initializes at most once per process.

**Environment gate (matches the other demos).** Add the following to your `.env` file (`deploy/.env` for the CLI):

```bash
MONOCLE_TRACING=true
MONOCLE_EXPORTERS=file          # file, console, okahu, s3, blob, gcs (default: file)
OKAHU_API_KEY=okh_xxxxxxxx      # required only for the `okahu` exporter
```

The CLI reads these at startup and initializes Monocle before the workflow runs.

**NAT telemetry exporter (canonical).** Add the `monocle` exporter to your workflow YAML; it initializes when the workflow builds:

```yaml
general:
  telemetry:
    tracing:
      monocle:
        _type: monocle
        workflow_name: nvidia-aiq   # optional, stamped on spans
        exporters: file             # optional; comma-separated, e.g. "file" or "file,okahu"
```

`OKAHU_API_KEY` is always read from the environment. `MONOCLE_EXPORTERS` is the default for the YAML `exporters` field, so the two paths agree unless you override it in YAML.

**Precedence.** The environment gate runs at CLI startup, before the workflow (and any YAML `monocle` exporter) is built. When both are set, the env gate wins and the YAML exporter finds Monocle already initialized. To drive the exporter list purely from YAML, leave `MONOCLE_TRACING` unset.

### Data handling

Traces capture span inputs and outputs verbatim -- prompts, tool arguments, and model responses -- plus token usage and timings. The `file` exporter keeps them on local disk and never rotates or cleans them up, so prune `.monocle/` periodically; the remote exporters (`okahu`, `s3`, `blob`, `gcs`) send that same data off-box, so enable only destinations you trust -- a warning is logged whenever an off-box exporter is active. An unknown exporter name fails fast with a clear error before any instrumentation. A missing `OKAHU_API_KEY` does **not** fail fast: the `okahu` exporter is skipped with a warning and the remaining exporters continue (if none remain, Monocle is skipped), so check the logs to confirm remote export is actually active.

### Configuration Reference

| Setting | Env / field | Default | Description |
| :-- | :-- | :-- | :-- |
| Enable | `MONOCLE_TRACING` (env) | off | Truthy gate for the environment opt-in path. |
| Exporters | `MONOCLE_EXPORTERS` (env) / `exporters` (YAML) | `file` | Comma-separated Monocle exporters, validated against `file, console, okahu, s3, blob, gcs`. |
| Okahu key | `OKAHU_API_KEY` (env) | -- | Required only when the `okahu` exporter is selected. |
| Workflow name | `workflow_name` (YAML) | `nvidia-aiq` | Workflow name Monocle stamps onto emitted spans. |

## Verbose Logging

For quick debugging without any external services, enable the built-in verbose callback logger. This prints detailed agent execution information directly to the console.

### Enable via CLI

```bash
./scripts/start_cli.sh --verbose
```

### Enable via YAML Config

```yaml
workflow:
  _type: chat_deepresearcher_agent
  verbose: true
```

### What Gets Logged

- Chain starts and completions (orchestrator routing, agent handoffs)
- LLM invocations with model name and token counts
- Tool calls with arguments and return values
- Reasoning content for frontier models that support it
