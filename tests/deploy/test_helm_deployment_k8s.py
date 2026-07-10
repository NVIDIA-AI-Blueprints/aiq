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

import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = REPO_ROOT / "deploy" / "helm" / "deployment-k8s"


def render_chart(*extra_args: str, namespace: str = "ns-aiq") -> list[dict[str, Any]]:
    result = subprocess.run(
        ["helm", "template", "aiq", str(CHART_PATH), "-n", namespace, *extra_args],
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def walk_values(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_values(item)


def test_default_chart_renders_referenced_configmaps_and_uses_user_supplied_secret():
    manifests = render_chart()

    rendered_configmaps = {
        manifest["metadata"]["name"] for manifest in manifests if manifest.get("kind") == "ConfigMap"
    }
    rendered_secrets = {manifest["metadata"]["name"] for manifest in manifests if manifest.get("kind") == "Secret"}

    referenced_configmaps = set()
    referenced_secrets = set()

    for manifest in manifests:
        for node in walk_values(manifest):
            if isinstance(node.get("configMap"), dict) and node["configMap"].get("name"):
                referenced_configmaps.add(node["configMap"]["name"])
            if isinstance(node.get("secretRef"), dict) and node["secretRef"].get("name"):
                referenced_secrets.add(node["secretRef"]["name"])
            if isinstance(node.get("secretKeyRef"), dict) and node["secretKeyRef"].get("name"):
                referenced_secrets.add(node["secretKeyRef"]["name"])

    assert referenced_configmaps <= rendered_configmaps
    assert referenced_secrets == {"aiq-credentials"}
    assert "aiq-credentials" not in rendered_secrets


def test_all_namespaced_resources_honor_release_namespace():
    """Regression test for #290: resources must use the Helm release namespace
    (``helm install -n <ns>``) instead of a hardcoded ``ns-aiq``, so ``helm
    install -n`` and GitOps operators (ArgoCD, Fleet) target the right namespace.
    """
    release_namespace = "my-namespace"
    manifests = render_chart(namespace=release_namespace)

    namespaced = [manifest for manifest in manifests if manifest.get("metadata", {}).get("namespace") is not None]

    # The chart must render at least one namespaced resource, otherwise this
    # test would pass vacuously if templating silently stopped emitting them.
    assert namespaced, "expected the chart to render namespaced resources"

    offenders = {
        (manifest.get("kind"), manifest["metadata"].get("name")): manifest["metadata"]["namespace"]
        for manifest in namespaced
        if manifest["metadata"]["namespace"] != release_namespace
    }
    assert not offenders, f"resources not pinned to release namespace {release_namespace!r}: {offenders}"


def test_chart_renders_app_host_aliases(tmp_path: Path):
    values_file = tmp_path / "host-aliases.yaml"
    values_file.write_text(
        """
aiq:
  apps:
    backend:
      hostAliases:
        - ip: "127.0.0.1"
          hostnames:
            - "aiq.local"
""",
        encoding="utf-8",
    )

    manifests = render_chart("-f", str(values_file))

    backend_deployment = next(
        manifest
        for manifest in manifests
        if manifest.get("kind") == "Deployment" and manifest["metadata"]["name"] == "aiq-backend"
    )

    assert backend_deployment["spec"]["template"]["spec"]["hostAliases"] == [
        {"ip": "127.0.0.1", "hostnames": ["aiq.local"]}
    ]


def test_default_chart_does_not_provision_or_configure_redis():
    manifests = render_chart()

    redis_resources = {
        (manifest.get("kind"), manifest.get("metadata", {}).get("name"))
        for manifest in manifests
        if manifest.get("metadata", {}).get("name", "").startswith("aiq-redis")
    }
    assert redis_resources == set()

    backend_deployment = next(
        manifest
        for manifest in manifests
        if manifest.get("kind") == "Deployment" and manifest["metadata"]["name"] == "aiq-backend"
    )
    backend_env = {
        item["name"] for item in backend_deployment["spec"]["template"]["spec"]["containers"][0].get("env", [])
    }
    assert backend_env.isdisjoint({"MCP_TOKEN_STORE_TYPE", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"})


def test_backend_uses_separate_liveness_and_readiness_endpoints():
    manifests = render_chart()

    backend_deployment = next(
        manifest
        for manifest in manifests
        if manifest.get("kind") == "Deployment" and manifest["metadata"]["name"] == "aiq-backend"
    )
    backend_container = backend_deployment["spec"]["template"]["spec"]["containers"][0]

    assert backend_container["livenessProbe"]["httpGet"]["path"] == "/live"
    assert backend_container["readinessProbe"]["httpGet"]["path"] == "/health"
