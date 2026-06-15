<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q with OpenShell

Use this page when you want copy/paste commands to run AI-Q with a named NVIDIA
OpenShell sandbox. The flow mirrors the normal README path: set up AI-Q, run one
OpenShell setup command, then start CLI or E2E mode with the OpenShell config.

Commands assume:

- You are running commands from the AI-Q repository root.
- Docker is running locally. On macOS, the setup script uses a running Colima
  socket when present; otherwise Docker Desktop must be installed and running.
  On Linux, the Docker daemon must be running and accessible to your user.

## Quick Start

```bash
cd /path/to/aiq-research-assistant

./scripts/setup.sh
cp deploy/.env.example deploy/.env
```

Edit `deploy/.env` and set the keys you need for research:

```bash
NVIDIA_API_KEY=nvapi-...
TAVILY_API_KEY=tvly-...
```

Create the OpenShell sandbox:

```bash
./scripts/setup_openshell.sh
```

That command checks the latest OpenShell release, asks which OpenShell version
to install, installs the `langchain-nvidia` OpenShell adapter, starts/verifies
the OpenShell gateway, asks you to choose a sandbox network policy, builds the
AI-Q sandbox image, and creates the named OpenShell sandbox `aiq-openshell-demo`.

Start interactive CLI mode:

```bash
./scripts/start_cli.sh --config_file configs/config_skills_openshell_deep.yml --verbose
```

Try this prompt:

```text
Use the data-table-analysis skill and execute Python in the sandbox for Q1=10, Q2=20, Q3=30. Return a markdown table with Q1, Q2, Q3, Total, and sources.
```

Start the full backend and web UI:

```bash
./scripts/start_e2e.sh --config_file configs/config_skills_openshell.yml
```

Then open:

```text
http://localhost:3000
```

Expected startup evidence:

```text
Knowledge retrieval initialized: backend=llamaindex
OpenShell sandbox READY: ... sandbox_name=aiq-openshell-demo ...
```

Expected table evidence:

```text
|   Q1 |   Q2 |   Q3 |   Total |
|-----:|-----:|-----:|--------:|
|   10 |   20 |   30 |      60 |
```

## Setup Options

The default sandbox is offline. This is the recommended baseline for AI-Q:
research tools collect data outside the sandbox, while sandbox code executes on
already gathered inputs.

By default, the setup command asks you to choose from a short policy menu. To
skip the prompt, pass a policy choice:

```bash
./scripts/setup_openshell.sh --policy offline
./scripts/setup_openshell.sh --policy research
./scripts/setup_openshell.sh --policy python-packages
./scripts/setup_openshell.sh --policy ai-dev
```

For a custom allowlist:

```bash
./scripts/setup_openshell.sh --policy custom --allow github,pypi,nvidia,tavily
```

Supported policy choices and custom services:

```bash
./scripts/setup_openshell.sh --list-policies
./scripts/setup_openshell.sh --list-services
```

Use an exact OpenShell version, or the latest released version:

```bash
./scripts/setup_openshell.sh --openshell-version 0.0.57
./scripts/setup_openshell.sh --openshell-version latest
./scripts/setup_openshell.sh --list-openshell-versions
```

The setup script verifies the version exists on PyPI and is at least `0.0.57`.
In the interactive prompt, pressing Enter selects `0.0.57`. If you type a
missing version, the script asks again.

By default, the script installs the adapter with:

```bash
uv pip install langchain-nvidia-openshell
```

Use a different `uv pip install` spec, such as an internal repo URL, or a local
`langchain-nvidia` checkout:

```bash
LANGCHAIN_NVIDIA_REPO='git+https://example.com/langchain-nvidia.git#subdirectory=libs/openshell' \
  ./scripts/setup_openshell.sh

./scripts/setup_openshell.sh \
  --langchain-nvidia /path/to/langchain-nvidia
```

If Docker is installed but not on `PATH`, pass it explicitly:

```bash
./scripts/setup_openshell.sh --docker-bin /path/to/docker
```

If the OpenShell gateway launcher is installed in a custom location:

```bash
./scripts/setup_openshell.sh --gateway-bin /path/to/openshell-gateway
```

## Policy Checks

Use the same setup command to recreate the sandbox with a restrictive policy:

```bash
./scripts/setup_openshell.sh --policy custom --allow github
```

Confirm the named sandbox exists:

```bash
.venv/bin/openshell sandbox list
```

Recreate the sandbox with PyPI allowed when package metadata access is needed:

```bash
./scripts/setup_openshell.sh --policy python-packages
```

Run a short AI-Q smoke test:

```bash
./scripts/start_cli.sh --config_file configs/config_skills_openshell_deep.yml --verbose
```

Prompt:

```text
Use the data-table-analysis skill and execute Python in the sandbox for Q1=10, Q2=20, Q3=30. Return a markdown table with Q1, Q2, Q3, Total, and sources.
```

## What the Setup Script Does

`scripts/setup_openshell.sh` is intentionally the only setup command you need
after AI-Q has a `.venv` and `deploy/.env`.

It performs these steps:

- Detects macOS or Linux.
- Verifies `uv`.
- Checks PyPI for released OpenShell versions from `0.0.57` through latest.
- Asks which OpenShell version to install; Enter selects `0.0.57`.
- Installs exactly the selected `openshell==<version>`.
- Installs the `langchain-nvidia` OpenShell adapter.
- Resolves Docker, including common Homebrew and Colima locations, then verifies
  the Docker daemon is reachable.
- Starts or verifies a local OpenShell gateway.
- Generates `configs/openshell/generated/aiq-openshell-policy.yaml`.
- Builds `aiq-openshell-demo:latest`.
- Creates the named sandbox `aiq-openshell-demo`.

The generated policy file is ignored by git. Durable reference policies live in
`configs/openshell/`.

## Clean Up

```bash
.venv/bin/openshell sandbox delete aiq-openshell-demo
pkill -f openshell-gateway
```
