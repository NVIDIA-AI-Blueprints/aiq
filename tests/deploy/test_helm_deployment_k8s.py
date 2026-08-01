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

import re
import subprocess
import tarfile
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = REPO_ROOT / "deploy" / "helm" / "deployment-k8s"
CHILD_CHART_DIR = REPO_ROOT / "deploy" / "helm" / "helm-charts-k8s" / "aiq"
CHILD_CHART_PATH = CHILD_CHART_DIR / "Chart.yaml"
PACKAGED_CHILD_CHART_PATH = CHART_PATH / "charts" / "aiq-0.0.5.tgz"
HELM_README_PATH = REPO_ROOT / "deploy" / "helm" / "README.md"
KUBERNETES_DOCS_PATH = REPO_ROOT / "docs" / "source" / "deployment" / "kubernetes.md"
OPENSEARCH_VALUES_PATH = REPO_ROOT / "deploy" / "helm" / "examples" / "aws-opensearch-serverless-values.yaml"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
EXPECTED_RELEASE_VERSION = "2.2.0"
EXPECTED_CHILD_CHART_VERSION = "0.0.5"


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


def test_release_version_matches_helm_chart_images_and_docs():
    with PYPROJECT_PATH.open("rb") as pyproject_file:
        package_version = tomllib.load(pyproject_file)["project"]["version"]

    parent_chart = yaml.safe_load((CHART_PATH / "Chart.yaml").read_text(encoding="utf-8"))
    child_chart = yaml.safe_load(CHILD_CHART_PATH.read_text(encoding="utf-8"))
    values = yaml.safe_load((CHART_PATH / "values.yaml").read_text(encoding="utf-8"))
    opensearch_values = yaml.safe_load(OPENSEARCH_VALUES_PATH.read_text(encoding="utf-8"))

    with tarfile.open(PACKAGED_CHILD_CHART_PATH, "r:gz") as archive:
        packaged_files = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            packaged_file = archive.extractfile(member)
            assert packaged_file is not None
            relative_path = Path(member.name).relative_to("aiq").as_posix()
            packaged_files[relative_path] = packaged_file.read()

    source_files = {
        path.relative_to(CHILD_CHART_DIR).as_posix(): path.read_bytes()
        for path in CHILD_CHART_DIR.rglob("*")
        if path.is_file()
    }
    packaged_child_chart = yaml.safe_load(packaged_files["Chart.yaml"])

    assert package_version == EXPECTED_RELEASE_VERSION
    assert parent_chart["version"] == EXPECTED_RELEASE_VERSION
    assert parent_chart["appVersion"] == EXPECTED_RELEASE_VERSION
    assert child_chart["appVersion"] == EXPECTED_RELEASE_VERSION
    assert child_chart["version"] == EXPECTED_CHILD_CHART_VERSION
    assert packaged_child_chart == child_chart
    assert packaged_files.keys() == source_files.keys()
    assert {path: content for path, content in packaged_files.items() if path != "Chart.yaml"} == {
        path: content for path, content in source_files.items() if path != "Chart.yaml"
    }
    assert parent_chart["dependencies"][0]["version"] == EXPECTED_CHILD_CHART_VERSION
    assert values["aiq"]["apps"]["backend"]["image"]["tag"] == EXPECTED_RELEASE_VERSION
    assert values["aiq"]["apps"]["frontend"]["image"]["tag"] == EXPECTED_RELEASE_VERSION
    assert opensearch_values["aiq"]["apps"]["backend"]["image"]["tag"] == EXPECTED_RELEASE_VERSION

    rendered_images = {
        manifest["metadata"]["name"]: manifest["spec"]["template"]["spec"]["containers"][0]["image"]
        for manifest in render_chart()
        if manifest.get("kind") == "Deployment"
    }
    assert rendered_images["aiq-backend"] == f"nvcr.io/nvidia/blueprint/aiq-agent:{EXPECTED_RELEASE_VERSION}"
    assert rendered_images["aiq-frontend"] == f"nvcr.io/nvidia/blueprint/aiq-frontend:{EXPECTED_RELEASE_VERSION}"

    expected_chart_archive = f"aiq2-web-{EXPECTED_RELEASE_VERSION}.tgz"
    chart_archive_pattern = re.compile(r"aiq2-web-[\w.-]+\.tgz")
    for documentation_path in (HELM_README_PATH, KUBERNETES_DOCS_PATH):
        documentation = documentation_path.read_text(encoding="utf-8")
        assert set(chart_archive_pattern.findall(documentation)) == {expected_chart_archive}
        assert f"**aiq2-web** version **{EXPECTED_RELEASE_VERSION}**" in documentation


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


def test_upload_limits_are_aligned_between_backend_and_frontend():
    values = yaml.safe_load((CHART_PATH / "values.yaml").read_text(encoding="utf-8"))
    backend_env = values["aiq"]["apps"]["backend"]["env"]
    frontend_env = values["aiq"]["apps"]["frontend"]["env"]
    upload_variables = {
        "FILE_UPLOAD_ACCEPTED_TYPES",
        "FILE_UPLOAD_MAX_SIZE_MB",
        "FILE_UPLOAD_MAX_FILE_COUNT",
    }

    assert {name: backend_env[name] for name in upload_variables} == {
        name: frontend_env[name] for name in upload_variables
    }


def test_backend_wires_default_on_deep_research_admission_limits():
    values = yaml.safe_load((CHART_PATH / "values.yaml").read_text(encoding="utf-8"))
    backend_env = values["aiq"]["apps"]["backend"]["env"]

    assert backend_env["AIQ_MAX_DEEP_RESEARCH_INPUT_CHARS"] == "32768"
    assert backend_env["AIQ_MAX_ACTIVE_DEEP_RESEARCH_JOBS_PER_PRINCIPAL"] == "5"
    assert backend_env["AIQ_MAX_ACTIVE_DEEP_RESEARCH_JOBS_GLOBAL"] == "50"
    assert backend_env["AIQ_MAX_DEEP_RESEARCH_SUBMISSIONS_PER_MINUTE"] == "20"


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
