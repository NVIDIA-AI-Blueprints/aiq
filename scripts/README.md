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
./scripts/start_cli.sh --config_file configs/config_skills_openshell_deep.yml --verbose
```

**Options:**

| Option | Description |
|--------|-------------|
| `--verbose` or `-v` | Enable verbose logging |
| `--config_file <path>` | Use a custom configuration file |

### `setup_openshell.sh` - OpenShell Sandbox Setup

Sets up NVIDIA OpenShell for the AI-Q sandbox path. Run this once before using
the OpenShell configs with `start_cli.sh` or `start_e2e.sh`.

```bash
./scripts/setup_openshell.sh
./scripts/start_cli.sh --config_file configs/config_skills_openshell_deep.yml --verbose
./scripts/start_e2e.sh --config_file configs/config_skills_openshell.yml
```

Useful version examples:

```bash
./scripts/setup_openshell.sh --openshell-version 0.0.57
./scripts/setup_openshell.sh --openshell-version latest
./scripts/setup_openshell.sh --list-openshell-versions
```

In the interactive version prompt, pressing Enter selects `0.0.57`.

By default, the setup script installs the OpenShell adapter with:

```bash
uv pip install langchain-nvidia-openshell
```

Set `LANGCHAIN_NVIDIA_REPO` or pass `--langchain-nvidia` to use another
`uv pip install` spec or a local checkout.

Useful policy examples:

```bash
./scripts/setup_openshell.sh --policy offline
./scripts/setup_openshell.sh --policy research
./scripts/setup_openshell.sh --policy python-packages
./scripts/setup_openshell.sh --policy custom --allow github,pypi,nvidia,tavily
```

See
[`docs/source/examples/skills-sandbox/openshell-manual.md`](../docs/source/examples/skills-sandbox/openshell-manual.md)
for copy/paste setup and policy check commands.

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
./scripts/start_e2e.sh --config_file configs/config_skills_openshell.yml
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
| `configs/config_skills_openshell.yml` | Server/E2E mode with LlamaIndex, DeepAgents skills, and OpenShell sandbox execution |
| `configs/config_skills_openshell_deep.yml` | Direct deep-research smoke-test mode with LlamaIndex, skills, and OpenShell |

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
