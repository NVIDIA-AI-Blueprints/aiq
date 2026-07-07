# Development Scripts

This directory contains helper scripts for developing and running the AI-Q blueprint.

## Available Scripts

### `setup.sh` - Initial Setup

Initializes the development environment, including Python dependencies and UI dependencies.

```bash
./scripts/setup.sh
```

### `dev.sh` - Development Helper

Main development command hub for common tasks.

```bash
./scripts/dev.sh <command>
```

**Commands:**

| Command | Description |
|---------|-------------|
| `test` | Run tests with pytest |
| `format` | Format code with isort and yapf |
| `lint` | Check code formatting (no changes) |
| `pre-commit` | Format code and run lint checks |
| `pylint` | Run pylint static analysis |
| `run` | Run the agent |
| `clean` | Remove build artifacts |
| `help` | Show help message |

### `start_cli.sh` - CLI Mode

Starts the agent in CLI mode with browser-based authentication.

```bash
./scripts/start_cli.sh
./scripts/start_cli.sh --verbose
```

**Options:**

| Option | Description |
|--------|-------------|
| `--verbose` or `-v` | Enable verbose logging |
| `--config_file <path>` | Use a custom configuration file |

### `setup_openshell.sh` - OpenShell Sandbox Setup

Sets up the experimental, local single-operator NVIDIA OpenShell path for AI-Q. Run this once before using
`configs/config_openshell.yml` with `start_cli.sh` or `start_e2e.sh`. It installs
the `openshell` SDK and the `langchain-nvidia-openshell` adapter, starts/verifies
the local OpenShell gateway, builds the sandbox image, generates a network policy,
and creates the named sandbox `aiq-openshell-demo`. Inference is unaffected (it
stays host-side, routed to NVIDIA Build); only generated code runs in the
network-blocked sandbox.

The generated configuration attaches all jobs to one named sandbox. Per-job directories
avoid filename collisions but do not isolate mutually untrusted jobs, and AI-Q does not
verify the provisioned policy when attaching. Do not treat this setup as a multi-tenant
security boundary.

```bash
./scripts/setup_openshell.sh --policy offline
./scripts/start_e2e.sh --config_file configs/config_openshell.yml
# or direct serve:
dotenv -f deploy/.env run .venv/bin/nat serve --config_file configs/config_openshell.yml --host 0.0.0.0 --port 8000
```

Useful version examples:

```bash
./scripts/setup_openshell.sh --openshell-version 0.0.72
./scripts/setup_openshell.sh --openshell-version latest
./scripts/setup_openshell.sh --list-openshell-versions
```

In the interactive version prompt, pressing Enter selects `0.0.72`.

The setup installs the `openshell` SDK plus the official `langchain-nvidia-openshell`
adapter (`OpenShellSandbox`), published on PyPI. The script installs it from PyPI by
default; set `LANGCHAIN_NVIDIA_REPO` or pass `--langchain-nvidia` to use another
`uv pip install` spec or a local checkout.

Useful policy examples:

```bash
./scripts/setup_openshell.sh --policy offline
./scripts/setup_openshell.sh --policy research
./scripts/setup_openshell.sh --policy python-packages
./scripts/setup_openshell.sh --policy custom --allow github,pypi,nvidia,tavily
```

Verify and clean up:

```bash
.venv/bin/openshell status
.venv/bin/openshell sandbox list          # expect: aiq-openshell-demo ... Ready
.venv/bin/openshell sandbox delete aiq-openshell-demo
# Inspect, then stop only the gateway you started (avoid killing other sessions):
pgrep -fl openshell-gateway        # find the PID(s)
kill <PID>                         # stop the specific process
```


### `start_server_in_debug_mode.sh` - Server Mode

Starts the NAT FastAPI server for deep research with async job support.

```bash
./scripts/start_server_in_debug_mode.sh
./scripts/start_server_in_debug_mode.sh--port 8080
./scripts/start_server_in_debug_mode.sh --config_file configs/config_web_frag.yml
```

**Options:**

| Option | Description |
|--------|-------------|
| `--port <port>` | Server port (default: 8000) |
| `--config_file <path>` | Use a custom configuration file |

**Available Endpoints:**

| Endpoint | Description |
|----------|-------------|
| `http://localhost:8000/docs` | API Documentation (Swagger UI) |
| `http://localhost:8000/debug` | Debug Console for testing async jobs |
| `http://localhost:8000/health` | Health check |
| `http://localhost:8000/v1/jobs/async/agents` | List available agent types |
| `http://localhost:8000/v1/jobs/async/submit` | Submit async job (POST) |
| `http://localhost:8000/v1/jobs/async/job/{id}/stream` | SSE stream for job progress |

### `start_as_skill.sh` - Agent Skill Backend

Starts the AI-Q API backend for use by Agent Skills such as `aiq-research`. This does not start the Next.js UI and disables the optional debug console.

```bash
./scripts/start_as_skill.sh
./scripts/start_as_skill.sh --port 8100
./scripts/start_as_skill.sh --config_file configs/config_web_default_llamaindex.yml
```

**Options:**

| Option | Description |
|--------|-------------|
| `--host <host>` | Server host (default: 0.0.0.0) |
| `--port <port>` | Server port (default: 8000) |
| `--config_file <path>` | Use an API-enabled configuration file |

**Available Endpoints:**

| Endpoint | Description |
|----------|-------------|
| `http://localhost:8000/docs` | API Documentation (Swagger UI) |
| `http://localhost:8000/health` | Health check |
| `http://localhost:8000/v1/jobs/async/agents` | List available agent types |
| `http://localhost:8000/v1/jobs/async/submit` | Submit async job (POST) |
| `http://localhost:8000/v1/jobs/async/job/{id}/stream` | SSE stream for job progress |

### `start_e2e.sh` - End-to-End Mode

Starts both backend and frontend for full WebSocket support and HITL workflows.

```bash
./scripts/start_e2e.sh
./scripts/start_e2e.sh --config_file configs/config_openshell.yml
```

**Services:**

| Service | URL |
|---------|-----|
| Backend | `http://localhost:8000` |
| Frontend | `http://localhost:3000` |

**Available Configs:**

| Config File | Description |
|-------------|-------------|
| `configs/config_cli_default.yml` | CLI mode with web search (default) |
| `configs/config_web_frag.yml` | Server/E2E mode with Foundational RAG |
| `configs/config_web_default_llamaindex.yml` | Server/E2E mode with LlamaIndex |
| `configs/config_skills.yml` | Deep research with DeepAgents skills + Modal sandbox |
| `configs/config_openshell.yml` | Experimental local single-operator OpenShell sandbox + artifact capture (run `setup_openshell.sh` first) |

## Development Workflow

When developing new features:

1. **Update code**: Make your changes to the codebase
2. **Test your changes**:
   ```bash
   ./scripts/dev.sh test
   ```
3. **Format and lint**:
   ```bash
   ./scripts/dev.sh pre-commit
   ```
4. **Run the agent**:
   ```bash
   ./scripts/start_cli.sh
   # OR
   ./scripts/start_as_skill.sh
   # OR
   ./scripts/start_e2e.sh
   ```
