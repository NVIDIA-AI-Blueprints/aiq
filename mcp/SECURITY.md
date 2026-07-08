<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# MCP release security checks

The standalone MCP profile is unauthenticated. Its job UUIDs are bearer
capabilities, and the endpoint must be protected by network policy or an
authenticated gateway outside a trusted environment. The full runtime model is
documented in
[Expose AI-Q as an MCP Server](../docs/source/integration/mcp-server.md#anonymous-capability-security).

## Reproducible dependency evidence

The required `Script Validation` CI job creates the Linux CPython 3.13
container's production-only environment for `aiq-mcp-server` and archives:

- a CycloneDX 1.5 dependency SBOM;
- the JSON result from the exact-lock `uv audit` gate; and
- a package-license inventory built from the exact production environment,
  including hashes of bundled license and NOTICE files without copying their
  text or local paths into CI logs.

The same checks can be reproduced from the repository root:

```bash
uv export --preview-features sbom-export \
  --frozen --package aiq-mcp-server --no-dev --no-default-groups \
  --format cyclonedx1.5 --output-file aiq-mcp.cdx.json >/dev/null

uv audit --preview-features audit-command,json-output \
  --frozen --no-dev --no-default-groups \
  --output-format json > aiq-mcp-vulnerabilities.json || test "$?" -eq 1

uv audit --preview-features audit-command,json-output \
  --frozen --no-dev --no-default-groups \
  --ignore-until-fixed GHSA-f4j7-r4q5-qw2c \
  --ignore-until-fixed GHSA-p4gq-832x-fm9v \
  --ignore-until-fixed PYSEC-2026-597 \
  --output-format json >/dev/null
```

```bash
UV_PROJECT_ENVIRONMENT=/tmp/aiq-mcp-release \
  uv sync --frozen --package aiq-mcp-server --no-dev --no-default-groups --no-editable
/tmp/aiq-mcp-release/bin/python mcp/scripts/check_license_inventory.py \
  aiq-mcp.cdx.json aiq-mcp-licenses.json
```

`uv audit` currently audits the complete production workspace lock, which is
stricter than the MCP-only CycloneDX closure. CI archives the unfiltered JSON,
including accepted findings, and runs the exception-aware command separately
as the pass/fail gate.

## No-fix vulnerability exceptions

Three canonical exceptions are accepted only while the advisory service
reports no fixed release. The `--ignore-until-fixed` form automatically turns
each exception back into a failure when a fix becomes available.

| Advisory | Transitive package | MCP reachability and compensating control |
|----------|--------------------|--------------------------------------------|
| `GHSA-f4j7-r4q5-qw2c` | ChromaDB | Present through the optional knowledge-layer backend. `config_mcp.yml` has no knowledge-retrieval function and the MCP application does not mount the Chroma server API named by the advisory. |
| `GHSA-p4gq-832x-fm9v` | NLTK | Present through optional knowledge-layer dependencies. The MCP source and public config do not call `nltk.data.load` or expose a caller-controlled NLTK resource path. |
| `PYSEC-2026-597` | NLTK | Same unreachable optional dependency path and controls as the canonical NLTK advisory above. |

The exact public function allowlist is enforced by
`mcp/tests/test_config_and_packaging.py`. Removing these transitive packages
cleanly requires a future minimal `aiq-agent` distribution or optional-dependency
refactor; uninstalling them after resolution would make package metadata
inaccurate.

The audit also reports archived project status for transitive packages. An
archived status is tracked as maintenance risk but is not itself a known
vulnerability. New vulnerability records still fail the required CI check.

## Security dependency override

The lock installs `cryptography==48.0.1` to replace the vulnerable OpenSSL
bundled in earlier wheels. `nvidia-nat-core==1.8.0` and `oci==2.178.0` still
declare upper bounds below 47, so the workspace's uv override intentionally
supersedes those stale bounds. The MCP config does not enable OCI or NAT
authentication.

`mcp/scripts/check_runtime_dependencies.py` performs the full installed
requirement check and permits only those two exact owner/version/dependency/
specifier tuples. It fails on any other incompatibility and also fails when an
upstream release makes an exception stale. The release image runs this check
before its import and plugin verification.

## License metadata policy

`mcp/scripts/check_license_inventory.py` fails when a direct runtime dependency
is absent, a package has no evidence, GPL/AGPL metadata appears, private runtime
or source metadata reappears, or a reviewed version/license/NOTICE hash changes.
`docx2txt` and `py-rust-stemmers` publish no license metadata; their exact
current wheels bundle MIT license files whose hashes are verified.

The inventory deliberately reports, but does not make a legal determination
about, the current LGPL dependencies, the ambiguous `nemoguardrails`
classifier, or the `fastembed` NOTICE entries mentioning CC-BY-NC and Gemma
terms. Those exact versions and file hashes remain marked
`manual_review_required`. They are inherited through broad optional AI-Q
dependency groups and are not configured by `config_mcp.yml`. Distribution
still requires the releasing organization's license/NOTICE policy review; a
new or changed finding fails CI instead of being silently accepted.

This is an engineering evidence and drift gate, not a general SPDX-license
allowlist or legal approval. The marker-excluded packages in the CycloneDX
document are not installed in the Linux CPython 3.13 release image and remain
listed as `platform_excluded`. Publishing the generic Python 3.11–3.13 wheel or
a Windows image requires a target-specific inventory and organizational
license/NOTICE review. The repository's curated `LICENSE-THIRD-PARTY` is not
used as the exact MCP dependency inventory; the archived JSON is.

The `aiq-mcp-server` wheel embeds the repository's Apache-2.0 license through
PEP 639 `license-files` metadata.
