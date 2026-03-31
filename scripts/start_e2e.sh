#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UI_DIR="$PROJECT_ROOT/frontends/ui"

# Default config file
CONFIG_FILE="configs/config_web_default_llamaindex.yml"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config_file)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --config_file <path>  Path to config file (default: configs/config_web_default_llamaindex.yml)"
            echo "  --help, -h            Show this help message"
            echo ""
            echo "Example:"
            echo "  $0 --config_file configs/config_web_default_llamaindex.yml"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate config file exists
if [ ! -f "$PROJECT_ROOT/$CONFIG_FILE" ]; then
    echo "Error: Config file not found: $CONFIG_FILE"
    echo "Usage: $0 --config_file <path>"
    echo "Example: $0 --config_file configs/config_web_default_llamaindex.yml"
    exit 1
fi

cleanup() {
    echo ""
    echo "Shutting down services..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "================================================"
echo "Starting AI-Q Blueprint (End-to-End)"
echo "================================================"
echo ""

check_env() {
    export AIQ_DEV_ENV=e2e
    echo "Set AIQ_DEV_ENV=e2e"

    if [ -f "./deploy/.env" ]; then
        set -a  # Automatically export all variables
        source ./deploy/.env
        set +a  # Stop auto-exporting
        echo "Backend environment file loaded (deploy/.env)"
    else
        echo "No deploy/.env file found (optional)"
    fi

    # Suppress Python warnings unless overridden by .env
    export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"

    # For local E2E, backend always runs on localhost:8000
    export BACKEND_URL="http://localhost:8000"
    export NEXT_PUBLIC_BACKEND_URL="http://localhost:8000"
    echo "Backend URL for e2e: $BACKEND_URL"
}

check_dependencies() {
    echo "Checking Python dependencies..."

    if ! python -c "import nat" 2>/dev/null; then
        echo "NAT not installed. Installing dependencies..."
        pip install -e .
    fi

    echo "Python dependencies installed"
}

check_ui_dependencies() {
    if [ ! -d "$UI_DIR" ]; then
        echo "UI directory not found at $UI_DIR"
        echo "Skipping frontend startup"
        return 1
    fi

    cd "$UI_DIR"

    if [ ! -d "node_modules" ]; then
        echo "Installing UI dependencies..."
        if command -v npm &> /dev/null; then
            npm ci
            echo "UI dependencies installed"
        else
            echo "npm not found. Skipping UI setup."
            echo "   Install Node.js 22+ to enable UI features"
            cd "$PROJECT_ROOT"
            return 1
        fi
    else
        echo "UI dependencies already installed"
    fi

    cd "$PROJECT_ROOT"
    return 0
}

start_backend() {
    echo ""
    echo "================================================"
    echo "Starting NAT Backend Server (Hot Reload Enabled)..."
    echo "================================================"
    echo ""
    echo "Backend will be available at: http://localhost:8000"
    echo "Backend will auto-reload on code changes"
    echo "Config: $CONFIG_FILE"
    echo ""

    nat serve --config_file "$CONFIG_FILE" --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    echo "Backend PID: $BACKEND_PID"
}

wait_for_backend() {
    echo "Waiting for backend to be ready..."
    local max_attempts=150
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -s -f http://localhost:8000/health > /dev/null 2>&1 || \
           curl -s -f http://localhost:8000/docs > /dev/null 2>&1; then
            echo "Backend is ready!"
            return 0
        fi
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done

    echo ""
    echo "Backend health check timeout after ${max_attempts}s"
    echo "   Continuing anyway - frontend may encounter initial connection errors"
    return 1
}

start_frontend() {
    if [ ! -d "$UI_DIR" ]; then
        return
    fi

    echo ""
    echo "================================================"
    echo "Starting UI Frontend..."
    echo "================================================"
    echo ""
    echo "Frontend will be available at: http://localhost:3000"
    echo ""

    cd "$UI_DIR"

    npm run dev &
    FRONTEND_PID=$!
    echo "Frontend PID: $FRONTEND_PID"

    cd "$PROJECT_ROOT"
}

main() {
    check_env
    echo ""

    check_dependencies
    echo ""

    if check_ui_dependencies; then
        HAS_UI=true
    else
        HAS_UI=false
    fi
    echo ""

    start_backend
    wait_for_backend

    if [ "$HAS_UI" = true ]; then
        start_frontend
    else
        echo ""
        echo "WARNING: Frontend will NOT be started."
        echo "   Reason: UI dependencies not available (missing npm or node_modules)"
        echo "   To fix: install Node.js 22+ and run 'npm ci' in frontends/ui/"
        echo "   The backend will still run at http://localhost:8000"
        echo ""
    fi

    echo ""
    echo "================================================"
    echo "Services Started"
    echo "================================================"
    echo ""
    echo "Backend: http://localhost:8000"
    if [ "$HAS_UI" = true ]; then
        echo "Frontend: http://localhost:3000"
    else
        echo "Frontend: SKIPPED (see warning above)"
    fi
    echo ""
    echo "Press Ctrl+C to stop all services"
    echo ""

    wait
}

main
