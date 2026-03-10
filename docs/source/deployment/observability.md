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
