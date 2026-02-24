#!/bin/bash
# Common development commands for AI-Q blueprint
set -euo pipefail
COMMAND=${1:-help}

case "$COMMAND" in
    test)
        echo "Running tests..."
        uv run pytest
        echo "Tests complete"
        ;;
    format)
        echo "Formatting code..."
        uv run ruff check --fix --select I src/aiq_agent/
        uv run yapf -i -r src/aiq_agent/
        echo "Code formatted"
        ;;
    lint)
        echo "Running linters..."
        echo "Running ruff..."
        uv run ruff check src/aiq_agent/
        echo "Running yapf..."
        uv run yapf -d -r src/aiq_agent/
        echo "Lint checks passed"
        ;;
    pre-commit)
        echo "Running pre-commit checks..."
        echo ""
        echo "Step 1: Formatting code..."
        uv run ruff check --fix --select I src/aiq_agent/
        uv run yapf -i -r src/aiq_agent/
        echo "Code formatted"
        echo ""
        echo "Step 2: Running lint checks..."
        uv run ruff check src/aiq_agent/
        uv run yapf -d -r src/aiq_agent/
        echo "All pre-commit checks passed"
        ;;
    ruff)
        echo "Running ruff..."
        uv run ruff check src/aiq_agent/
        ;;
    clean)
        echo "Cleaning build artifacts..."
        rm -rf build/ dist/ *.egg-info
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        find . -type f -name '*.pyc' -delete
        find . -type f -name '*.pyo' -delete
        find . -type f -name '*~' -delete
        echo "Cleaned"
        ;;
    help|*)
        echo "AI-Q Blueprint - Development Commands"
        echo "=============================================="
        echo ""
        echo "Usage: ./scripts/dev.sh <command>"
        echo ""
        echo "Commands:"
        echo "  test        - Run tests with pytest"
        echo "  format      - Format code with ruff (imports) and yapf"
        echo "  lint        - Check code with ruff and yapf (no changes)"
        echo "  pre-commit  - Format code and run lint checks"
        echo "  ruff        - Run ruff linter"
        echo "  clean       - Remove build artifacts"
        echo "  help        - Show this help message"
        echo ""
        ;;
esac

