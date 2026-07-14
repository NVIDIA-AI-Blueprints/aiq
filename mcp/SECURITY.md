<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# MCP release security checks

The standalone MCP profile is unauthenticated. Its job UUIDs are bearer
capabilities, and the endpoint must be protected by network policy or an
authenticated gateway outside a trusted environment. The server bounds a single
request's workflow input by rejecting `submit_query` calls longer than
`AIQ_MCP_MAX_QUERY_CHARS` (default 8000) characters before any job is enqueued;
submission rate limiting is deployment-owned and belongs at the gateway or
ingress in front of the endpoint. The full runtime model is documented in
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
  --project mcp --frozen --no-dev --no-default-groups \
  --format cyclonedx1.5 --output-file aiq-mcp.cdx.json >/dev/null

uv audit --preview-features audit-command,json-output \
  --project mcp --frozen --no-dev --no-default-groups \
  --output-format json > aiq-mcp-vulnerabilities.json || test "$?" -eq 1

uv audit --preview-features audit-command,json-output \
  --project mcp --frozen --no-dev --no-default-groups \
  --ignore-until-fixed GHSA-f4j7-r4q5-qw2c \
  --output-format json >/dev/null
```

```bash
UV_PROJECT_ENVIRONMENT=/tmp/aiq-mcp-release \
  uv sync --project mcp --frozen --no-dev --no-default-groups --no-editable
/tmp/aiq-mcp-release/bin/python mcp/scripts/check_license_inventory.py \
  aiq-mcp.cdx.json aiq-mcp-licenses.json
```

`uv audit` audits the isolated `mcp/uv.lock`; it does not audit the root AI-Q
workspace lock. CI archives the unfiltered MCP JSON, including accepted
findings, and runs the exception-aware command separately as the pass/fail
gate.

## No-fix vulnerability exception

One canonical exception is accepted only while the advisory service reports no
fixed release. The `--ignore-until-fixed` form automatically turns the
exception back into a failure when a fix becomes available.

| Advisory | Transitive package | MCP reachability and compensating control |
|----------|--------------------|--------------------------------------------|
| `GHSA-f4j7-r4q5-qw2c` | ChromaDB | Present through the optional knowledge-layer backend. `config_mcp.yml` has no knowledge-retrieval function and the MCP application does not mount the Chroma server API named by the advisory. |

The exact public function allowlist is enforced by
`mcp/tests/test_config_and_packaging.py`. Removing this transitive package
cleanly requires a future minimal `aiq-agent` distribution or optional-dependency
refactor; uninstalling it after resolution would make package metadata
inaccurate.

The MCP project requires `nltk>=3.10.0` so its production lock includes NLTK's
path-security fixes. NLTK 3.10 adds `defusedxml`; the MCP project constrains
that dependency to the stable 0.7 release line because its prerelease policy
would otherwise select a 0.8 release candidate. NLTK no longer requires an
audit exception.

The audit also reports archived project status for transitive packages. An
archived status is tracked as maintenance risk but is not itself a known
vulnerability. New vulnerability records still fail the required CI check.

## Security dependency override

The isolated MCP lock installs `cryptography==48.0.1` to replace the vulnerable
OpenSSL bundled in earlier wheels. `nvidia-nat-core==1.8.0` and
`oci==2.178.0` still declare upper bounds below 47, so the MCP project's uv
override intentionally supersedes those stale bounds. The MCP config does not
enable OCI or NAT authentication. The root AI-Q lock is separate and keeps
`cryptography>=46.0.6,<47` so its environment remains within NAT's declared
range.

This override is security policy for the frozen MCP project and release
container, not a functional requirement of MCP or a published package
constraint. Only the frozen `mcp/uv.lock` profile carries the audited 48.0.1
guarantee.

`mcp/scripts/check_runtime_dependencies.py` performs the full installed
requirement check and permits only those two exact owner/version/dependency/
specifier tuples. It fails on any other incompatibility and also fails when an
upstream release makes an exception stale. The release image runs the same
script with `--verify-imports`, which additionally imports every runtime
module, asserts the exact `mcp` and `nvidia-nat-core` release pins, and checks
the `tavily_web_search` NAT plugin entry point.

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
listed as `platform_excluded`. Publishing an image for another platform requires
a target-specific inventory and organizational license/NOTICE review. The
repository's curated `LICENSE-THIRD-PARTY` is not used as the exact MCP
dependency inventory; the archived JSON is.

The supported distributable artifact is the release container built from the
repository root. The frozen source project is the supported development path.
`aiq-mcp-server` and its repository-local dependency closure are not published
as generic Python wheels. CI builds the MCP wheel only as an internal packaging
check and verifies that it embeds the repository's Apache-2.0 license through
PEP 639 `license-files` metadata.
