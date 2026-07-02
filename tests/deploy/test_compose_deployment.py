# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from nat.utils.io.yaml_tools import yaml_load

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "deploy" / "compose" / "docker-compose.yaml"
PER_USER_AUTH_COMPOSE_PATH = REPO_ROOT / "deploy" / "compose" / "docker-compose.per-user-auth.yaml"
MCP_CONFIG_PATH = REPO_ROOT / "configs" / "config_web_frag_mcp_auth.yml"


def load_compose() -> dict[str, Any]:
    with COMPOSE_PATH.open(encoding="utf-8") as compose_file:
        return yaml.safe_load(compose_file)


def test_default_compose_does_not_provision_or_configure_redis():
    compose = load_compose()
    services = compose["services"]
    backend = services["aiq-agent"]

    assert "redis" not in services
    assert "redis-data" not in compose.get("volumes", {})
    assert "redis" not in backend.get("depends_on", {})

    backend_env = {
        entry.split("=", maxsplit=1)[0] for entry in backend.get("environment", []) if isinstance(entry, str)
    }
    assert backend_env.isdisjoint({"MCP_TOKEN_STORE_TYPE", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"})


def test_per_user_auth_compose_adds_private_redis_token_store(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker is required to validate Compose merge behavior")

    compose_version = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        check=False,
        text=True,
    )
    if compose_version.returncode != 0:
        pytest.skip("docker compose is required to validate Compose merge behavior")

    # The runtime env file is intentionally untracked. Render from a temporary
    # copy so this merge test works in a clean checkout without developer secrets.
    base_compose = load_compose()
    base_compose["services"]["aiq-agent"].pop("env_file", None)
    test_compose_path = tmp_path / "docker-compose.yaml"
    test_compose_path.write_text(yaml.safe_dump(base_compose), encoding="utf-8")

    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(REPO_ROOT / "deploy" / ".env.example"),
            "-f",
            str(test_compose_path),
            "-f",
            str(PER_USER_AUTH_COMPOSE_PATH),
            "config",
            "--format",
            "json",
            "--no-env-resolution",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    compose = json.loads(result.stdout)
    backend = compose["services"]["aiq-agent"]
    redis = compose["services"]["redis"]

    assert "redis-data" in compose["volumes"]
    assert backend["depends_on"]["redis"]["condition"] == "service_healthy"
    assert backend["environment"]["CONFIG_FILE"] == "/app/configs/config_web_frag_mcp_auth.yml"
    assert backend["environment"]["MCP_TOKEN_STORE_TYPE"] == "redis"
    assert backend["environment"]["REDIS_HOST"] == "redis"
    assert backend["environment"]["REDIS_PORT"] == "6379"
    assert "ports" not in redis


def test_mcp_example_config_accepts_an_optional_external_redis_password(monkeypatch):
    monkeypatch.delenv("MCP_TOKEN_STORE_TYPE", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    without_password = yaml_load(MCP_CONFIG_PATH)["object_stores"]["mcp_token_store"]
    assert without_password["_type"] == "aiq_sqlite"
    assert without_password["password"] is None

    monkeypatch.setenv("MCP_TOKEN_STORE_TYPE", "redis")
    test_password = "managed-redis-password"  # pragma: allowlist secret
    monkeypatch.setenv("REDIS_PASSWORD", test_password)
    with_password = yaml_load(MCP_CONFIG_PATH)["object_stores"]["mcp_token_store"]
    assert with_password["_type"] == "redis"
    assert with_password["password"] == test_password
