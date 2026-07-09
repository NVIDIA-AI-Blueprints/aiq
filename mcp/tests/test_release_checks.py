# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Release-hygiene policy tests."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_license_inventory.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT), run_name="license_policy_test")
_AMBIGUOUS_METADATA = _NAMESPACE["_AMBIGUOUS_METADATA"]
_BUNDLED_FILE_ONLY = _NAMESPACE["_BUNDLED_FILE_ONLY"]
_DIRECT_RUNTIME_DEPENDENCIES = _NAMESPACE["_DIRECT_RUNTIME_DEPENDENCIES"]
_PLATFORM_EXCLUDED = _NAMESPACE["_PLATFORM_EXCLUDED"]
_WEAK_COPYLEFT = _NAMESPACE["_WEAK_COPYLEFT"]
_evidence_fingerprint = _NAMESPACE["_evidence_fingerprint"]
validate_inventory = _NAMESPACE["validate_inventory"]
validate_sbom = _NAMESPACE["validate_sbom"]


def _row(name: str, version: str = "1.0", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "locked_version": version,
        "resolution_marker": None,
        "installed_version": version,
        "version_matches": True,
        "evidence_kind": "expression",
        "license_expression": "Apache-2.0",
        "license_field": None,
        "license_classifiers": [],
        "license_files": [],
        "notice_review_flags": [],
    }
    row.update(overrides)
    return row


def _inventory(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    rows = [_row(name) for name in sorted(_DIRECT_RUNTIME_DEPENDENCIES)]
    for name, version in _BUNDLED_FILE_ONLY:
        row = _row(
            name,
            version,
            evidence_kind="bundled-license-file-only",
            license_expression=None,
            license_files=[
                {
                    "filename": "LICENSE.txt" if name == "docx2txt" else "LICENSE",
                    "sha256": f"{name}-license-hash",
                }
            ],
        )
        rows.append(row)
        monkeypatch.setitem(_BUNDLED_FILE_ONLY, (name, version), _evidence_fingerprint(row))
    for (name, version), marker in _PLATFORM_EXCLUDED.items():
        rows.append(
            _row(
                name,
                version,
                installed_version=None,
                version_matches=None,
                evidence_kind="not-installed-in-target-environment",
                license_expression=None,
                resolution_marker=marker,
            )
        )
    for (name, version), expected in _AMBIGUOUS_METADATA.items():
        row = _row(
            name,
            version,
            license_expression=None,
            license_field="Apache License",
            license_classifiers=["Other/Proprietary License"],
            license_files=[{"filename": "LICENSE", "sha256": f"{name}-license-hash"}],
            notice_review_flags=["cc-by-nc", "gemma-terms"] if expected["reason"] == "notice-content" else [],
        )
        rows.append(row)
        monkeypatch.setitem(expected, "fingerprint", _evidence_fingerprint(row))
    for name, version in _WEAK_COPYLEFT:
        row = _row(
            name,
            version,
            license_expression="LGPL-3.0-only",
            license_files=[{"filename": "LICENSE", "sha256": f"{name}-license-hash"}],
        )
        rows.append(row)
        monkeypatch.setitem(_WEAK_COPYLEFT, (name, version), _evidence_fingerprint(row))
    return {"components": rows}


def test_license_inventory_surfaces_exact_review_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = _inventory(monkeypatch)
    validation = validate_inventory(inventory)

    assert validation["components"] == len(inventory["components"])
    assert validation["bundled_license_file_only"] == [
        "docx2txt==0.9",
        "py-rust-stemmers==0.1.8",
    ]
    assert {item["reason"] for item in validation["manual_review_required"]} == {
        "ambiguous-metadata",
        "notice-content",
        "weak-copyleft",
    }


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_row("new-package", evidence_kind="missing", license_expression=None), "missing license evidence"),
        (_row("new-package", license_expression="GPLv3"), "strong-copyleft dependency metadata"),
        (
            _row(
                "new-package",
                license_expression=None,
                license_classifiers=["Other/Proprietary License"],
            ),
            "unreviewed proprietary or NOTICE metadata",
        ),
    ],
)
def test_license_inventory_rejects_unreviewed_evidence(
    row: dict[str, Any],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _inventory(monkeypatch)
    inventory["components"].append(row)
    with pytest.raises(ValueError, match=message):
        validate_inventory(inventory)


def test_license_inventory_rejects_changed_reviewed_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = _inventory(monkeypatch)
    fastembed = next(row for row in inventory["components"] if row["name"] == "fastembed")
    fastembed["license_files"] = [{"sha256": "changed"}]

    with pytest.raises(ValueError, match="reviewed license or NOTICE evidence changed"):
        validate_inventory(inventory)


def test_license_inventory_rejects_extra_reviewed_file(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = _inventory(monkeypatch)
    docx2txt = next(row for row in inventory["components"] if row["name"] == "docx2txt")
    docx2txt["license_files"].append({"filename": "COPYING-GPL", "sha256": "new-hash"})

    with pytest.raises(ValueError, match="unreviewed bundled-only license evidence"):
        validate_inventory(inventory)


def test_license_inventory_rejects_weak_metadata_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = _inventory(monkeypatch)
    psycopg = next(row for row in inventory["components"] if row["name"] == "psycopg")
    psycopg["license_expression"] = "LGPL-2.1-only"

    with pytest.raises(ValueError, match="unreviewed weak-copyleft evidence"):
        validate_inventory(inventory)


def test_license_inventory_requires_every_direct_runtime_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = _inventory(monkeypatch)
    inventory["components"] = [
        row for row in inventory["components"] if row["name"] != next(iter(_DIRECT_RUNTIME_DEPENDENCIES))
    ]

    with pytest.raises(ValueError, match="direct runtime dependencies missing"):
        validate_inventory(inventory)


def test_sbom_contract_accepts_the_exact_approved_local_component_set() -> None:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "aiq-mcp-server", "version": "0.1.0"}},
        "components": [
            {"name": "aiq-agent", "version": "2.0.0"},
            {"name": "knowledge-layer", "version": "1.0.0"},
            {"name": "tavily-web-search", "version": "1.0.0"},
            {
                "name": "asyncpg",
                "version": "0.31.0",
                "purl": "pkg:pypi/asyncpg@0.31.0",
            },
        ],
    }

    validate_sbom(sbom)


def test_sbom_contract_requires_every_approved_local_component() -> None:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "aiq-mcp-server", "version": "0.1.0"}},
        "components": [
            {"name": "aiq-agent", "version": "2.0.0"},
            {"name": "knowledge-layer", "version": "1.0.0"},
        ],
    }

    with pytest.raises(ValueError, match="local component set differs"):
        validate_sbom(sbom)


def test_sbom_contract_rejects_non_pypi_dependency_source() -> None:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "aiq-mcp-server", "version": "0.1.0"}},
        "components": [{"name": "private-runtime", "version": "1.0"}],
    }

    with pytest.raises(ValueError, match="unapproved local dependency source"):
        validate_sbom(sbom)


def test_sbom_contract_rejects_private_sdk_name_from_public_index() -> None:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"name": "aiq-mcp-server", "version": "0.1.0"}},
        "components": [
            {
                "name": "maas-sdk",
                "version": "2.4.1",
                "purl": "pkg:pypi/maas-sdk@2.4.1",
            }
        ],
    }

    with pytest.raises(ValueError, match="forbidden private SDK dependency"):
        validate_sbom(sbom)
