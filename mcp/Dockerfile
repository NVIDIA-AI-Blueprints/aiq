# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build from the repository root:
#   docker build --target release -f mcp/Dockerfile -t aiq-mcp-server:local .

ARG PYTHON_IMAGE=python:3.13.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION=0.11.26

WORKDIR /app

RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_PYTHON_DOWNLOADS=never

# The root lock owns this workspace. Copy every workspace manifest that uv must
# discover, plus only the source/config needed by the MCP dependency closure.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY sources/ ./sources/
COPY frontends/aiq_api/pyproject.toml ./frontends/aiq_api/
COPY frontends/cli/pyproject.toml ./frontends/cli/
COPY frontends/debug/pyproject.toml ./frontends/debug/
COPY frontends/benchmarks/freshqa/pyproject.toml ./frontends/benchmarks/freshqa/
COPY frontends/benchmarks/deepsearch_qa/pyproject.toml ./frontends/benchmarks/deepsearch_qa/
COPY mcp/LICENSE mcp/pyproject.toml mcp/README.md ./mcp/
COPY mcp/src/ ./mcp/src/
COPY mcp/scripts/check_runtime_dependencies.py ./mcp/scripts/check_runtime_dependencies.py
COPY configs/config_mcp.yml ./configs/config_mcp.yml

# Install exactly the production dependency closure from the frozen public
# workspace lock. Workspace packages are installed as wheels, not editables, so
# the release image needs only the virtual environment and runtime config.
RUN --mount=type=cache,id=aiq-mcp-uv,target=/root/.cache/uv,sharing=locked \
    uv sync \
        --frozen \
        --package aiq-mcp-server \
        --no-dev \
        --no-default-groups \
        --no-editable \
        --python /usr/local/bin/python

RUN /opt/venv/bin/python mcp/scripts/check_runtime_dependencies.py \
    && /opt/venv/bin/python -c "import importlib; from importlib.metadata import entry_points, version; [importlib.import_module(name) for name in ('aiq_mcp', 'aiq_mcp.server', 'aiq_mcp.jobs', 'aiq_mcp.job_store', 'aiq_mcp.workflow_runner', 'aiq_agent.common', 'tavily_web_search', 'knowledge_layer', 'asyncpg')]; assert version('mcp') == '1.27.2'; assert version('nvidia-nat-core') == '1.8.0'; assert any(ep.name == 'tavily_web_search' for ep in entry_points(group='nat.plugins')); print('AI-Q MCP runtime verified')"

FROM ${PYTHON_IMAGE} AS release

LABEL org.opencontainers.image.title="NVIDIA AI-Q MCP Server" \
      org.opencontainers.image.description="Public FastMCP server for the NVIDIA AI-Q Blueprint" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 aiq \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/aiq --shell /usr/sbin/nologin aiq

WORKDIR /app

COPY --from=builder --chown=10001:10001 /opt/venv /opt/venv
COPY --chown=10001:10001 configs/config_mcp.yml /app/configs/config_mcp.yml
COPY --chown=10001:10001 LICENSE /licenses/LICENSE

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/venv/bin:$PATH"
ENV HOME=/home/aiq
ENV XDG_CACHE_HOME=/home/aiq/.cache
ENV AIQ_MCP_CONFIG=/app/configs/config_mcp.yml
ENV AIQ_MCP_HOST=0.0.0.0
ENV AIQ_MCP_PORT=9001
ENV AIQ_MCP_PATH=/mcp
ENV AIQ_MCP_WORKERS=1
ENV AIQ_MCP_LOG_LEVEL=INFO

USER 10001:10001

EXPOSE 9001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import http.client, os; connection = http.client.HTTPConnection('127.0.0.1', int(os.environ.get('AIQ_MCP_PORT', '9001')), timeout=3); connection.request('GET', '/health'); response = connection.getresponse(); response.read(); connection.close(); raise SystemExit(0 if response.status == 200 else 1)"]

ENTRYPOINT ["python", "-m", "aiq_mcp.server"]
