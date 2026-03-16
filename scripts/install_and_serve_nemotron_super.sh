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
#
# Installs vLLM and serves NVIDIA-Nemotron-3-Super-120B with tensor parallelism.
# Requires: super_v3_reasoning_parser.py in REPO_ROOT (or set REASONING_PARSER_PATH).
# Run from repo root: ./scripts/install_and_serve_nemotron_super.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# Defaults (all overridable via environment variables)
# ---------------------------------------------------------------------------
PYTHON="${PYTHON:-python3}"
VLLM_DIR="${VLLM_DIR:-$REPO_ROOT/vllm}"
VENV_DIR="${VENV_DIR:-$VLLM_DIR/.venv}"
REASONING_PARSER_PATH="${REASONING_PARSER_PATH:-$REPO_ROOT/super_v3_reasoning_parser.py}"

MODEL_NAME="${MODEL_NAME:-nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16}"
SERVED_NAME="${SERVED_NAME:-nemotron-super}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
TP_SIZE="${TP_SIZE:-8}"
PP_SIZE="${PP_SIZE:-1}"
DP_SIZE="${DP_SIZE:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-200000}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.9}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "[vllm] $*"; }

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Install vLLM into a local venv and serve Nemotron-3-Super-120B via the
OpenAI-compatible API.

Options:
  -h, --help    Show this help and exit

Configuration via environment variables:

  PYTHON                Python interpreter             (default: python3)
  VLLM_DIR              Directory for the vLLM venv    (default: <repo>/vllm)
  VENV_DIR              Virtual-env path               (default: VLLM_DIR/.venv)
  REASONING_PARSER_PATH Path to reasoning parser plugin (default: <repo>/super_v3_reasoning_parser.py)
  HOST                  Bind address                   (default: 0.0.0.0)
  PORT                  Bind port                      (default: 8080)
  TP_SIZE               Tensor-parallel GPUs           (default: 8)
  PP_SIZE               Pipeline-parallel size          (default: 1)
  DP_SIZE               Data-parallel size              (default: 1)
  MAX_MODEL_LEN         Max sequence length            (default: 200000)
  GPU_MEM_UTIL          GPU memory utilisation          (default: 0.9)

Example:
  TP_SIZE=4 PORT=8000 ./scripts/install_and_serve_nemotron_super.sh
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help) usage ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

# OS check — vLLM with CUDA requires Linux
if [[ "$(uname -s)" != "Linux" ]]; then
    log "WARNING: vLLM GPU serving is only supported on Linux."
    log "Detected OS: $(uname -s). The installation may fail or run in CPU-only mode."
    read -r -p "[vllm] Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
fi

# Python check
if ! command -v "$PYTHON" &>/dev/null; then
    echo "Error: Python interpreter '$PYTHON' not found." >&2
    echo "Install Python 3.9+ or set PYTHON to the correct path." >&2
    exit 1
fi

# GPU check (nvidia-smi)
if command -v nvidia-smi &>/dev/null; then
    GPU_COUNT=$(nvidia-smi -L 2>/dev/null | wc -l)
    log "Detected $GPU_COUNT GPU(s)"
    if [[ "$GPU_COUNT" -lt "$TP_SIZE" ]]; then
        log "WARNING: TP_SIZE=$TP_SIZE but only $GPU_COUNT GPU(s) detected."
        log "Set TP_SIZE to match your hardware (e.g. TP_SIZE=$GPU_COUNT)."
    fi
else
    log "WARNING: nvidia-smi not found — cannot verify GPU availability."
fi

# ---------------------------------------------------------------------------
# Virtual environment & vLLM install
# ---------------------------------------------------------------------------
mkdir -p "$VLLM_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

log "Installing vLLM in $VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install vllm

# ---------------------------------------------------------------------------
# Reasoning parser — download if missing
# ---------------------------------------------------------------------------
if [[ ! -f "$REASONING_PARSER_PATH" ]]; then
    log "Downloading reasoning parser to $REASONING_PARSER_PATH"
    curl -fsSL -o "$REASONING_PARSER_PATH" \
        "https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16/raw/main/super_v3_reasoning_parser.py"
fi

# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------
log "Starting vLLM serve: $MODEL_NAME (TP=$TP_SIZE) on ${HOST}:${PORT}"
exec "$VENV_DIR/bin/vllm" serve "$MODEL_NAME" \
    --async-scheduling \
    --dtype auto \
    --kv-cache-dtype fp8 \
    --tensor-parallel-size "$TP_SIZE" \
    --pipeline-parallel-size "$PP_SIZE" \
    --data-parallel-size "$DP_SIZE" \
    --swap-space 0 \
    --trust-remote-code \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --enable-chunked-prefill \
    --served-model-name "$SERVED_NAME" \
    --max-model-len "$MAX_MODEL_LEN" \
    --host "$HOST" \
    --port "$PORT" \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser-plugin "$REASONING_PARSER_PATH" \
    --reasoning-parser super_v3
