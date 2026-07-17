<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example: CLI with Local NIMs

Run the full research pipeline interactively from the command line using self-hosted NIM models. This is useful for air-gapped environments, custom fine-tuned models, or reducing latency by running inference locally.

This example is based on `configs/config_cli_default.yml` with modifications to point LLMs at locally-hosted NIM containers. To use local NIMs, copy the default config to `configs/config_cli_local_nims.yml` and update the `base_url` fields as shown below.

## Prerequisites

You need Docker and NVIDIA GPUs with sufficient VRAM to run the NIM containers. Check the Nemotron Super model card and support matrix for current self-hosted hardware requirements.

## Running NIM Containers

Start the NIM model server locally using Docker:

```bash
# Pull and run the Nemotron NIM container
# Adjust --gpus and CUDA_VISIBLE_DEVICES for your hardware
docker run -d \
  --name nemotron-nim \
  --gpus all \
  -p 8001:8000 \
  -e NVIDIA_API_KEY="${NVIDIA_API_KEY}" \
  nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b:latest
```

Verify the model is ready:

```bash
curl http://localhost:8001/v1/models
```

For multi-model setups (for example, separate intent and research models), run additional containers on different ports:

```bash
# Smaller model for intent classification
docker run -d \
  --name nemotron-mini-nim \
  --gpus '"device=1"' \
  -p 8002:8000 \
  -e NVIDIA_API_KEY="${NVIDIA_API_KEY}" \
  nvcr.io/nim/nvidia/nemotron-mini-4b-instruct:latest
```

## Configuration

```yaml
# configs/config_cli_local_nims.yml
# Copy of config_cli_default.yml with base_url pointing to local NIM containers

general:
  telemetry:
    logging:
      console:
        _type: console
        level: INFO
    # Optional: trace to local Phoenix for debugging
    # tracing:
    #   phoenix:
    #     _type: phoenix
    #     endpoint: http://localhost:6006/v1/traces
    #     project: local-dev

# ===========================================================================
# LLMs - pointing to local NIM containers
# ===========================================================================
# The key difference from cloud configs: base_url points to localhost
# instead of integrate.api.nvidia.com. No NVIDIA_API_KEY is needed for
# inference (only for pulling the container image).
llms:
  nemotron_llm_intent:
    _type: nim
    model_name: nvidia/nemotron-3-super-120b-a12b
    base_url: "http://localhost:8001/v1"   # <-- Local NIM
    temperature: 0.5
    top_p: 0.9
    max_tokens: 4096
    num_retries: 3
    chat_template_kwargs:
      enable_thinking: true

  nemotron_super_llm:
    _type: nim
    model_name: nvidia/nemotron-3-super-120b-a12b
    base_url: "http://localhost:8001/v1"   # <-- Local NIM
    temperature: 0.1
    top_p: 0.3
    max_tokens: 16384
    num_retries: 3
    chat_template_kwargs:
      enable_thinking: true

# ===========================================================================
# Functions
# ===========================================================================
functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true

  paper_search_tool:
    _type: paper_search
    max_results: 5
    serper_api_key: ${SERPER_API_KEY}

  intent_classifier:
    _type: intent_classifier
    llm: nemotron_llm_intent
    tools:
      - web_search_tool
      - paper_search_tool

  clarifier_agent:
    _type: clarifier_agent
    llm: nemotron_super_llm
    tools:
      - web_search_tool
    max_turns: 3
    log_response_max_chars: 2000
    verbose: true

  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_super_llm
    tools:
      - web_search_tool
    max_llm_turns: 10
    max_tool_iterations: 5

  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_super_llm
    tools:
      - paper_search_tool
      - advanced_web_search_tool

# ===========================================================================
# Workflow
# ===========================================================================
workflow:
  _type: chat_deepresearcher_agent
  enable_escalation: true
  enable_clarifier: true
  checkpoint_db: ${AIQ_CHECKPOINT_DB:-./checkpoints.db}
```

## Required Environment Variables

```bash
# Only needed for pulling NIM container images (not for inference)
export NVIDIA_API_KEY="nvapi-..."  # pragma: allowlist secret

# Web search still requires API keys (runs externally)
export TAVILY_API_KEY="tvly-..."   # pragma: allowlist secret
export SERPER_API_KEY="..."
```

## How to Run

```bash
# Interactive CLI mode (recommended)
./scripts/start_cli.sh --config_file configs/config_cli_local_nims.yml

# Single query mode
dotenv -f deploy/.env run .venv/bin/nat run \
  --config_file configs/config_cli_local_nims.yml \
  --input "What are the latest advances in quantum error correction?"
```

The CLI script starts an interactive session. Type your research query and the system will:

1. Classify the intent (shallow vs deep)
2. Ask a focused clarification only when the request is genuinely ambiguous; the clarifier does not ask you to approve a plan
3. For deep queries, build an internal structured plan and run independent research queries concurrently
4. Show research tool activity in real time
5. Have the writer synthesize the captured evidence into the requested output shape

### Example Session

```
> What are the latest advances in quantum error correction?

[Intent: shallow]
[Tool: web_search] Searching: "quantum error correction advances 2026"
[Tool: web_search] Searching: "quantum error correction codes recent breakthroughs"
[Tool: web_search] Found 5 results

# Quantum Error Correction: Recent Advances

...
```

## Tips for Local NIMs

- **GPU memory**: Monitor with `nvidia-smi`. The 30B model needs ~40 GB VRAM.
- **Startup time**: NIM containers take 2--5 minutes to load the model on first start. Wait until `/v1/models` returns a response.
- **Multiple GPUs**: Use `--gpus '"device=0,1"'` to spread across GPUs, or run separate containers per GPU for different model roles.
- **Networking**: If running inside Docker Compose, use container names instead of `localhost` for `base_url`.
- **num_retries**: Lower retry counts (3 vs 5) are appropriate for local NIMs since failures are less likely to be transient.
