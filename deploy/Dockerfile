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

# =============================================================================
# Multi-stage build for AI-Q Blueprint Backend
# =============================================================================
#
# Build targets:
#   docker build --target dev -t aiq:dev .     # Development (includes CLI)
#   docker build --target release -t aiq:prod . # Production (web only, validates env)
#
# =============================================================================

# =============================================================================
# Stage 1: Builder (shared between dev and release)
# =============================================================================
FROM nvcr.io/nvidia/base/ubuntu:jammy-20251013 AS builder

WORKDIR /app

# Install system dependencies and Python 3.12
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    tzdata \
    build-essential \
    curl \
    git \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m ensurepip --upgrade \
    && python3.12 -m pip install --no-cache-dir uv \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3

RUN uv venv /app/.venv --python /usr/local/bin/python

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV UV_PYTHON=/app/.venv/bin/python

# Copy workspace configuration and lockfile
COPY pyproject.toml uv.lock ./

# Copy all source packages
COPY src/ ./src/
COPY sources/ ./sources/
COPY frontends/aiq_api/ ./frontends/aiq_api/
COPY frontends/cli/ ./frontends/cli/
COPY frontends/debug/ ./frontends/debug/
COPY configs/ ./configs/
# Only copy runtime scripts from deploy/ — never copy the full directory
# to avoid leaking .env, Helm charts, compose files, or other dev artifacts.
COPY deploy/entrypoint.py deploy/start_web.py ./deploy/

# Install dependencies using uv sync
RUN uv sync --frozen --no-dev --no-install-workspace

# Install workspace packages (without CLI for base)
RUN uv pip install --no-deps -e . \
    && uv pip install --no-deps -e ./sources/google_scholar_paper_search \
    && uv pip install --no-deps -e ./sources/tavily_web_search \
    && uv pip install --no-deps -e "./sources/knowledge_layer[all]" \
    && uv pip install --no-deps -e ./frontends/aiq_api \
    && uv pip install "psycopg[binary]>=3.0.0"

RUN /app/.venv/bin/python -c "import aiq_api; import knowledge_layer; print('✓ Base packages installed')"

RUN chmod +x /app/deploy/start_web.py \
    && mkdir -p /app/data \
    && chown -R 1000:1000 /app

# =============================================================================
# Stage 2: Development (includes CLI)
# =============================================================================
FROM builder AS dev-builder

# Install CLI and debug UI for development
RUN uv pip install --no-deps -e ./frontends/cli \
    && uv pip install --no-deps -e ./frontends/debug

RUN /app/.venv/bin/python -c "import aiq_api; import aiq_research_cli; import aiq_debug; import knowledge_layer; print('✓ All packages installed')"

# =============================================================================
# Stage 3: Development runtime
# =============================================================================
FROM nvcr.io/nvidia/distroless/python:3.12-v3.5.3 AS dev

WORKDIR /app

COPY --from=dev-builder /app /app

USER 1000:1000

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]

# =============================================================================
# Stage 4: Release (production - no CLI)
# =============================================================================
FROM nvcr.io/nvidia/distroless/python:3.12-v3.5.3 AS release

WORKDIR /app

# Copy from base builder (no CLI)
COPY --from=builder /app /app

USER 1000:1000

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/app/.venv/bin:$PATH"
ENV APP_ENV=production

EXPOSE 8000

ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]
