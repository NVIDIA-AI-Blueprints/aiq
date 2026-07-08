# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Production dependency-consistency policy tests."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_runtime_dependencies.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT), run_name="dependency_policy_test")
validate_dependency_records = _NAMESPACE["validate_dependency_records"]


def _records() -> list[dict[str, object]]:
    return [
        {
            "name": "nvidia-nat-core",
            "version": "1.8.0",
            "requires": ["cryptography<47,>=46.0.6"],
        },
        {
            "name": "oci",
            "version": "2.178.0",
            "requires": ["cryptography (<47.0.0,>=3.2.1)"],
        },
        {
            "name": "cryptography",
            "version": "48.0.1",
            "requires": [],
        },
    ]


def test_exact_security_overrides_are_visible() -> None:
    result = validate_dependency_records(_records(), {"cryptography": "48.0.1"})

    assert result == {
        "security_overrides": [
            "nvidia-nat-core==1.8.0 requires cryptography<47,>=46.0.6; using 48.0.1",
            "oci==2.178.0 requires cryptography<47.0.0,>=3.2.1; using 48.0.1",
        ]
    }


def test_unexpected_incompatibility_fails() -> None:
    records = _records()
    records.append({"name": "new-package", "version": "1.0", "requires": ["cryptography<40"]})

    with pytest.raises(ValueError, match="unexpected dependency incompatibilities"):
        validate_dependency_records(records, {"cryptography": "48.0.1"})


def test_changed_override_fails_closed() -> None:
    records = _records()
    records[0]["version"] = "1.8.1"

    with pytest.raises(ValueError, match="unexpected dependency incompatibilities"):
        validate_dependency_records(records, {"cryptography": "48.0.1"})


def test_resolved_override_must_be_removed_from_policy() -> None:
    records = _records()
    records[0]["requires"] = ["cryptography>=48.0.1"]

    with pytest.raises(ValueError, match="stale security override exceptions"):
        validate_dependency_records(records, {"cryptography": "48.0.1"})


def test_missing_dependency_fails() -> None:
    with pytest.raises(ValueError, match="missing installed dependency"):
        validate_dependency_records(_records(), {})
