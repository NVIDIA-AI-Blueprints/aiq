<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Swapping Models

LLMs are defined in the `llms` section and referenced by agents and tools. You can swap NIM models, change parameters, or add alternative providers.

**Example: NIM model (default)**

```yaml
llms:
  nemotron_nano_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.7
    top_p: 0.7
    max_tokens: 8192
    num_retries: 5
```

**Example: NIM with thinking (for example, for deep research)**

```yaml
llms:
  nemotron_nano_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 1.0
    top_p: 1.0
    max_tokens: 128000
    chat_template_kwargs:
      enable_thinking: true
```

**Model roles:** The workflow maps LLMs to roles (orchestrator, researcher, planner, etc.) through the `LLMProvider`. In YAML you assign which named LLM each agent uses (for example, `orchestrator_llm: nemotron_nano_llm`, `llm: nemotron_nano_llm`). Use different keys in `llms` and point agents at them to swap models per role.

## Using Downloadable NIMs (Self-Hosted)

By default, configs use NVIDIA's hosted NIM API (`integrate.api.nvidia.com`). You can also run NIMs locally or on your own infrastructure for lower latency, data privacy, or offline use.

### 1. Find Downloadable NIMs

Browse available NIMs at [build.nvidia.com](https://build.nvidia.com/explore/discover). Each model page includes a "Self-Host" tab with Docker pull commands and setup instructions.

### 2. Run a NIM Locally

```bash
# Example: run Nemotron on port 8080
docker run --gpus all -p 8080:8000 \
  nvcr.io/nim/nvidia/nemotron-3-nano-30b-a3b:latest
```

Refer to the [NIM documentation](https://docs.nvidia.com/nim/) for GPU requirements, environment variables, and multi-GPU setup.

### 3. Update Your Config

Change `base_url` to point to your local NIM instance instead of the hosted API. The `model_name` stays the same. You can remove `api_key` since local NIMs typically don't require one.

```yaml
llms:
  nemotron_nano_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "http://localhost:8080/v1"    # local NIM
    temperature: 0.7
    max_tokens: 8192
    num_retries: 5
```

```{note}
**Nemotron Super — Build Endpoint Availability:** Nemotron Super (`nvidia/nemotron-3-super-120b-a12b`) is compatible and tested with AIQ, but Build API endpoints have limited availability due to high demand (HTTP 429 or 503 responses). The default configs use Nemotron Nano for reliability. You can uncomment `nemotron_super_llm` in your config if the endpoint is accessible. For production deployments requiring consistent throughput, self-hosting via a [Brev Launchable](https://brev.nvidia.com/launchable/deploy?launchableID=nvidia-official-nemotron-super-49b-v1) is recommended.
```

You can mix hosted and local NIMs in the same config -- for example, use a local NIM for the high-volume shallow researcher and a hosted NIM for the orchestrator:

```yaml
llms:
  local_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "http://localhost:8080/v1"
    temperature: 0.7
    max_tokens: 8192

  hosted_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 1.0
    max_tokens: 128000

functions:
  shallow_research_agent:
    _type: shallow_research_agent
    llm: local_llm          # fast, local inference
    # ...

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: hosted_llm   # hosted for deep thinking
    # ...
```

## NVIDIA Hosted API Considerations

The default configs use `https://integrate.api.nvidia.com/v1`, which is NVIDIA's developer-facing hosted NIM API. This service is convenient for getting started but has limitations that matter for production use and long-running evaluations.

### Known Limitations

**Model availability**

Models served through `integrate.api.nvidia.com` are subject to change:

- Model versions may be updated or deprecated without notice
- Partner-hosted models (for example, `openai/gpt-oss-120b`) depend on third-party availability and may be removed from the NVIDIA-hosted endpoint
- Check [build.nvidia.com](https://build.nvidia.com/explore/discover) for current model availability and changelogs

### Mitigation Strategies

| Issue | Recommended action |
|-------|-------------------|
| Rate limiting during benchmarks | Lower `max_concurrency` in eval config; add delays between requests |
| Frequent `504` timeouts | Increase `timeout` parameter; switch to a self-hosted NIM for that role |
| Model removed or deprecated | Update `model_name` to the replacement model; pin a tested model version when possible |
| Production reliability requirements | Use self-hosted NIMs or an NVIDIA Enterprise API agreement with SLA guarantees |

For self-hosted NIM setup, refer to [Using Downloadable NIMs](#using-downloadable-nims-self-hosted) above.
