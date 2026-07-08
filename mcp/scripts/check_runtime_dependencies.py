# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate the production environment, including exact security overrides."""

from __future__ import annotations

import json
from importlib.metadata import distributions
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

_ALLOWED_INCOMPATIBILITIES = {
    ("nvidia-nat-core", "1.8.0", "cryptography", "48.0.1", "<47,>=46.0.6"),
    ("oci", "2.178.0", "cryptography", "48.0.1", "<47.0.0,>=3.2.1"),
}


def validate_dependency_records(
    records: list[dict[str, Any]],
    installed_versions: dict[str, str],
) -> dict[str, list[str]]:
    environment = default_environment()
    environment["extra"] = ""
    conflicts: set[tuple[str, str, str, str, str]] = set()

    for record in records:
        owner = canonicalize_name(str(record["name"]))
        owner_version = str(record["version"])
        for requirement_text in record.get("requires", []):
            requirement = Requirement(str(requirement_text))
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            dependency = canonicalize_name(requirement.name)
            installed_version = installed_versions.get(dependency)
            if installed_version is None:
                raise ValueError(f"missing installed dependency: {owner} requires {dependency}")
            if requirement.specifier and Version(installed_version) not in requirement.specifier:
                conflicts.add(
                    (
                        owner,
                        owner_version,
                        dependency,
                        installed_version,
                        str(requirement.specifier),
                    )
                )

    unexpected = sorted(conflicts - _ALLOWED_INCOMPATIBILITIES)
    if unexpected:
        raise ValueError(f"unexpected dependency incompatibilities: {unexpected}")
    stale = sorted(_ALLOWED_INCOMPATIBILITIES - conflicts)
    if stale:
        raise ValueError(f"stale security override exceptions: {stale}")

    return {
        "security_overrides": [
            f"{owner}=={owner_version} requires {dependency}{specifier}; using {installed_version}"
            for owner, owner_version, dependency, installed_version, specifier in sorted(conflicts)
        ]
    }


def validate_environment() -> dict[str, list[str]]:
    installed = list(distributions())
    installed_versions = {
        canonicalize_name(dist.metadata["Name"]): dist.version for dist in installed if dist.metadata.get("Name")
    }
    records = [
        {
            "name": dist.metadata["Name"],
            "version": dist.version,
            "requires": list(dist.requires or ()),
        }
        for dist in installed
        if dist.metadata.get("Name")
    ]
    return validate_dependency_records(records, installed_versions)


def main() -> int:
    try:
        result = validate_environment()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
