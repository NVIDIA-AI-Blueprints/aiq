# AIQ Deploy Skill

## Overview

`aiq-deploy` helps agents install, configure, start, validate, troubleshoot, and stop a local or self-hosted NVIDIA
AI-Q Blueprint deployment. It prepares an AI-Q backend that can be handed to `aiq-research`.

## Prerequisites

Users need:

- Git access to `https://github.com/NVIDIA-AI-Blueprints/aiq`.
- Docker Engine with Docker Compose v2 for the default local deployment.
- Python 3.11+ and `uv` for local process or CLI mode.
- Node.js 20+ and `npm` for browser UI development mode.
- `kubectl` 1.28+, Helm 3.12+, and Kubernetes cluster access for Helm mode.
- `NVIDIA_API_KEY` for hosted-model usage.
- At least one supported search provider key, such as `TAVILY_API_KEY`, `SERPER_API_KEY`, or `EXA_API_KEY`, for web
  research workflows.
- Network access to GitHub, NVIDIA-hosted model endpoints, and selected search providers.

## Quick Start

Copy or verify the local environment file:

```bash
test -f deploy/.env || cp deploy/.env.example deploy/.env
git check-ignore deploy/.env
```

Start a backend-only Docker Compose deployment for `aiq-research`:

```bash
cd deploy/compose
BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml config --quiet
BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml up -d --build aiq-agent
curl -sf http://localhost:8000/health
```

Expected result: Docker Compose starts `aiq-agent` and its dependencies, and the health endpoint returns successfully.

## Structure

```text
aiq-deploy/
|-- SKILL.md
|-- LICENSE
|-- README.md
|-- evals/
|   `-- evals.json
`-- references/
    |-- cli.md
    |-- configs.md
    |-- docker-compose.md
    |-- end-to-end-validation.md
    |-- env-and-secrets.md
    |-- frag.md
    |-- kubernetes-helm.md
    |-- local-web.md
    |-- locate-or-clone.md
    |-- shutdown.md
    |-- skill-backend.md
    |-- troubleshooting.md
    `-- validation.md
```

`SKILL.md` contains the agent-facing workflow. `references/` contains detailed paths for specific deployment modes and
troubleshooting.

## Version Compatibility

This skill is designed for NVIDIA AI-Q Blueprint version 2.1.0. It follows semantic version compatibility:

- Major versions must match.
- Blueprint minor version must be equal to or newer than the skill minor version.
- Patch version differences do not affect compatibility.

## License

Copyright (c) 2026 NVIDIA Corporation. All rights reserved.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for full license text.

## Copyright

Copyright (c) 2026 NVIDIA Corporation. All rights reserved.
