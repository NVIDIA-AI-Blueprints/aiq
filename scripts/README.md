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

### `start_e2e.sh` - End-to-End Mode

Starts both backend and frontend for full WebSocket support and HITL workflows.

```bash
./scripts/start_e2e.sh
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
| `configs/config_web_frag.yml` | Server/E2E mode with Foundational RAG (default) |
| `configs/config_web_default_llamaindex.yml` | Server/E2E mode with LlamaIndex |

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
   ./scripts/start_e2e.sh
   ```
