#!/bin/bash
# Setup script for AI-Q blueprint development environment

set -euo pipefail

echo "=== AI-Q Blueprint Development Setup ==="
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "uv installed"
else
    echo "uv is already installed"
fi

# Resolve uv binary for non-interactive shells (e.g., Jupyter).
# The installer may place uv in ~/.local/bin, which isn't always on PATH yet.
UV_BIN="$(command -v uv || true)"
if [ -z "${UV_BIN}" ] && [ -x "${HOME}/.local/bin/uv" ]; then
    export PATH="${HOME}/.local/bin:${PATH}"
    UV_BIN="${HOME}/.local/bin/uv"
fi

if [ -z "${UV_BIN}" ]; then
    echo "Error: uv was not found after installation."
    echo "Add uv to PATH (typically ${HOME}/.local/bin) and re-run setup."
    exit 1
fi

# Create virtual environment
echo ""
echo "Creating virtual environment..."
"${UV_BIN}" venv --python 3.13 --seed .venv
echo "Virtual environment created"

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source .venv/bin/activate

# Install core framework with dev dependencies (uses uv.lock to pin versions)
echo ""
echo "Installing core framework with dev dependencies..."
"${UV_BIN}" sync --dev
echo "Core framework installed"

# Install frontends (--no-deps: dependencies already resolved by uv sync)
echo ""
echo "Installing frontends..."
"${UV_BIN}" pip install --no-deps -e ./frontends/cli
"${UV_BIN}" pip install --no-deps -e ./frontends/debug
"${UV_BIN}" pip install --no-deps -e ./frontends/aiq_api
echo "Frontends installed (CLI, Debug, AI-Q API)"

# Install benchmarks
echo ""
echo "Installing benchmarks..."
"${UV_BIN}" pip install --no-deps -e ./frontends/benchmarks/freshqa
"${UV_BIN}" pip install --no-deps -e ./frontends/benchmarks/deepsearch_qa
echo "Benchmarks installed"

# Install data sources
echo ""
echo "Installing data sources..."
"${UV_BIN}" pip install --no-deps -e ./sources/tavily_web_search
"${UV_BIN}" pip install --no-deps -e ./sources/google_scholar_paper_search
"${UV_BIN}" pip install --no-deps -e "./sources/knowledge_layer[llamaindex,foundational_rag]"
echo "Data Sources installed"

# Setup pre-commit
echo ""
echo "Setting up pre-commit hooks..."
pre-commit install
echo "Pre-commit hooks installed"

# Setup environment file
echo ""
if [ ! -f deploy/.env ]; then
    echo "Creating .env file from template..."
    cp deploy/.env.example deploy/.env
    echo "Please edit deploy/.env and add your NVIDIA_API_KEY"
else
    echo ".env file already exists"
fi

# Setup UI dependencies (optional)
echo ""
if [ -d "frontends/ui" ]; then
    echo "Setting up UI dependencies..."
    cd frontends/ui

    if command -v npm &> /dev/null; then
        npm ci
        echo "UI dependencies installed"
    else
        echo "npm not found. Skipping UI setup."
        echo "   Install Node.js 22+ to enable UI features"
    fi

    cd ../..
else
    echo "UI directory not found at frontends/ui"
fi

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Activate virtual environment: source .venv/bin/activate"
echo "2. Add your NVIDIA_API_KEY to deploy/.env"
echo "3. Run the agent:"
echo "   - CLI mode:        ./scripts/start_cli.sh"
echo "   - Server mode:     ./scripts/start_server_in_debug_mode.sh"
echo "   - End-to-End (UI): ./scripts/start_e2e.sh"
echo ""
