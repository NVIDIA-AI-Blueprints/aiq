# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Phase 5 public container, Compose, and database deployment contracts."""

from __future__ import annotations

import hashlib
import runpy
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "mcp" / "Dockerfile"
_COMPOSE_FILE = _REPO_ROOT / "deploy" / "compose" / "docker-compose.mcp.yaml"
_INIT_SQL = _REPO_ROOT / "mcp" / "deploy" / "init-mcp-db.sql"
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"
_SMOKE_SCRIPT = _REPO_ROOT / "mcp" / "scripts" / "protocol_smoke.py"

_EXPECTED_SQL_HASH = "05c27bca7385f6127017bee72ae067d02a49849db73b483d42868aaaf90341c7"  # pragma: allowlist secret
_MCP_ENVIRONMENT = {
    "AIQ_CHECKPOINT_DB",
    "AIQ_MCP_ALLOWED_HOSTS",
    "AIQ_MCP_ALLOWED_ORIGINS",
    "AIQ_MCP_CONFIG",
    "AIQ_MCP_CORS_ORIGINS",
    "AIQ_MCP_HOST",
    "AIQ_MCP_LOG_LEVEL",
    "AIQ_MCP_PATH",
    "AIQ_MCP_PORT",
    "AIQ_MCP_SHALLOW_INLINE_WAIT_SECONDS",
    "AIQ_MCP_WORKERS",
    "NVIDIA_API_KEY",
    "TAVILY_API_KEY",
}
_EXPECTED_COPY_LINES = (
    "COPY pyproject.toml uv.lock README.md ./",
    "COPY src/ ./src/",
    "COPY sources/ ./sources/",
    "COPY frontends/aiq_api/pyproject.toml ./frontends/aiq_api/",
    "COPY frontends/cli/pyproject.toml ./frontends/cli/",
    "COPY frontends/debug/pyproject.toml ./frontends/debug/",
    "COPY frontends/benchmarks/freshqa/pyproject.toml ./frontends/benchmarks/freshqa/",
    "COPY frontends/benchmarks/deepsearch_qa/pyproject.toml ./frontends/benchmarks/deepsearch_qa/",
    "COPY mcp/LICENSE mcp/pyproject.toml mcp/README.md ./mcp/",
    "COPY mcp/src/ ./mcp/src/",
    "COPY mcp/scripts/check_runtime_dependencies.py ./mcp/scripts/check_runtime_dependencies.py",
    "COPY configs/config_mcp.yml ./configs/config_mcp.yml",
    "COPY --from=builder --chown=10001:10001 /opt/venv /opt/venv",
    "COPY --chown=10001:10001 configs/config_mcp.yml /app/configs/config_mcp.yml",
    "COPY --chown=10001:10001 LICENSE /licenses/LICENSE",
)


def _normalized_sql() -> str:
    lines = []
    for raw_line in _INIT_SQL.read_text().splitlines():
        line = raw_line.rstrip()
        if line.strip() and not line.lstrip().startswith("--"):
            lines.append(line)
    return "\n".join(lines) + "\n"


def test_release_dockerfile_is_public_reproducible_and_non_root() -> None:
    text = _DOCKERFILE.read_text()

    assert "ARG PYTHON_IMAGE=python:3.13.12-slim-bookworm" in text
    assert "ARG UV_VERSION=0.11.26" in text
    assert text.count("FROM ${PYTHON_IMAGE}") == 2
    assert "AS builder" in text
    assert "AS release" in text
    assert "uv sync" in text
    assert "--frozen" in text
    assert "--package aiq-mcp-server" in text
    assert "--no-dev" in text
    assert "--no-default-groups" in text
    assert "--no-editable" in text
    assert "COPY . " not in text
    assert "USER 10001:10001" in text
    assert "EXPOSE 9001" in text
    assert "HEALTHCHECK" in text
    assert 'ENTRYPOINT ["python", "-m", "aiq_mcp.server"]' in text
    assert "configs/config_mcp.yml" in text
    assert "AIQ_MCP_CONFIG=/app/configs/config_mcp.yml" in text
    assert "COPY --chown=10001:10001 LICENSE /licenses/LICENSE" in text
    assert "/opt/venv/bin/python mcp/scripts/check_runtime_dependencies.py" in text
    assert tuple(line.strip() for line in text.splitlines() if line.startswith("COPY ")) == _EXPECTED_COPY_LINES


def test_init_sql_preserves_reference_schema_and_upgrade_history() -> None:
    normalized = _normalized_sql()
    assert hashlib.sha256(normalized.encode()).hexdigest() == _EXPECTED_SQL_HASH
    assert "CREATE TABLE IF NOT EXISTS mcp_jobs" in normalized
    assert "idx_mcp_jobs_runner_state" in normalized
    assert "VALUES ('aiq_maas_mcp', 1)" in normalized
    assert "VALUES ('aiq_maas_mcp', 2)" in normalized


def test_compose_stack_is_isolated_explicit_and_health_gated() -> None:
    compose = yaml.safe_load(_COMPOSE_FILE.read_text())
    assert compose["name"] == "aiq-mcp"
    assert set(compose["services"]) == {"postgres", "aiq-mcp"}
    assert set(compose["volumes"]) == {"mcp-postgres-data"}
    assert set(compose["networks"]) == {"aiq-mcp-network"}
    assert compose["networks"]["aiq-mcp-network"].get("internal") is not True

    for service in compose["services"].values():
        assert "container_name" not in service
        assert "env_file" not in service
        assert service["networks"] == ["aiq-mcp-network"]
        assert "healthcheck" in service

    postgres = compose["services"]["postgres"]
    assert postgres["image"] == "postgres:16-alpine"
    assert postgres["environment"]["POSTGRES_PASSWORD"] == "local_mcp_password"  # pragma: allowlist secret
    assert postgres["ports"] == ["127.0.0.1:${AIQ_MCP_POSTGRES_PORT:-1234}:5432"]
    assert "mcp-postgres-data:/var/lib/postgresql/data" in postgres["volumes"]
    assert "../../mcp/deploy/init-mcp-db.sql:/docker-entrypoint-initdb.d/init-mcp-db.sql:ro" in postgres["volumes"]

    mcp = compose["services"]["aiq-mcp"]
    assert mcp["build"] == {"context": "../..", "dockerfile": "mcp/Dockerfile", "target": "release"}
    assert set(mcp["environment"]) == _MCP_ENVIRONMENT
    assert (
        mcp["environment"]["AIQ_CHECKPOINT_DB"]
        == "postgresql://aiq:local_mcp_password@postgres:5432/aiq_jobs"  # pragma: allowlist secret
    )
    assert mcp["environment"]["AIQ_MCP_PORT"] == "9001"
    assert mcp["environment"]["AIQ_MCP_CONFIG"] == "/app/configs/config_mcp.yml"
    assert mcp["ports"] == ["127.0.0.1:${AIQ_MCP_PUBLISHED_PORT:-9001}:9001"]
    assert mcp["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert mcp["security_opt"] == ["no-new-privileges:true"]
    assert mcp["cap_drop"] == ["ALL"]


def test_deployment_context_excludes_env_files_and_includes_package_readmes() -> None:
    lines = set(_DOCKERIGNORE.read_text().splitlines())
    assert {".env", ".env.*", "**/.env", "**/.env.*"} <= lines
    assert {
        "!README.md",
        "!mcp/README.md",
        "!sources/knowledge_layer/README.md",
        "!sources/tavily_web_search/README.md",
    } <= lines


def test_protocol_smoke_script_is_importable_without_running() -> None:
    namespace = runpy.run_path(str(_SMOKE_SCRIPT), run_name="deployment_smoke_test")
    assert namespace["EXPECTED_SERVER_NAME"] == "aiq_deep_research"
    assert namespace["EXPECTED_TOOLS"] == {"get_final_report", "poll_query", "submit_query"}
    assert namespace["EXPECTED_HEALTH_STATUS"] == "ready"
    assert namespace["UNKNOWN_JOB_ID"] == "00000000-0000-4000-8000-000000000000"
    assert namespace["FORBIDDEN_REQUEST_HEADERS"] == {"authorization"}
