<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deep Research Sandbox + Artifact Runtime

Provider-neutral sandbox execution for agent-generated code, plus a durable artifact
runtime that harvests generated files (charts, CSVs, notebooks) so they survive the
sandbox and can be served to the UI, embedded in reports, or downloaded via the skill CLI.

Design pattern: **sandbox-as-tool**. AI-Q keeps the orchestrator, auth, tools, event
store, and report state in-process; only generated code runs remotely. Secrets and
data-source credentials never enter the sandbox.

## Architecture

```text
config YAML (sandbox.provider + providers.<name>)
        -> SandboxConfig (config.py)
        -> registry.create_sandbox_backend  --(fail-closed capability gate)-->  SandboxProvider
                                                                                     |
DeepAgentsRuntime (deepagents_runtime.py) holds the provider and composes:           |
   CompositeBackend(default = provider, routes = {/shared/, /skills/ -> StateBackend})
        - workdir (default route): real sandbox FS, reached via execute. The EFFECTIVE
          workdir is per-job: <configured workdir>/<job_id> (e.g. /sandbox/<job_id>), with
          artifacts nested at <job_id>/aiq-artifacts. See "Workspace isolation" below.
        - /shared/, /skills/: in-process virtual FS (durable text, never the sandbox)
   ArtifactManager (artifacts/manager.py): download_files -> validate -> ArtifactStore -> SSE
```

## Workspace organization and isolation limits

The effective working directory is scoped per job to `<configured workdir>/<job_id>`, and
the artifact directory is nested under it at `<job_id>/aiq-artifacts`. The provider base
creates these on session start (`_prepare_workspace`, an idempotent `mkdir -p`) and the
runtime injects them into prompts/skills as `sandbox_workdir`/`sandbox_artifact_dir`. This
prevents accidental filename collisions and keeps harvesting scoped to the current job.

Modal and OpenShell both create a fresh physical sandbox for each job. OpenShell parses the
configured policy with the installed SDK schema, applies it in the creation `SandboxSpec`,
waits for `READY`, and verifies the authoritative effective policy source, protobuf content,
OpenShell hash, and active revision before exposing the backend. A positive status version
alone is never treated as attestation. An optional `expected_policy_version` provides an exact
revision pin. Any creation or attestation failure closes the owning SDK context so the partially
created sandbox is deleted.

Zero generic `current_policy_version` or `active_version` values are treated as unreported only
when the LOADED revision plus effective config agree on the same positive version, source,
protobuf content, and deterministic hash. Every positive reported version remains subject to
exact agreement. An effective policy that remains Pending beyond `policy_load_timeout_seconds`
fails with `policy_status_inconsistent`; AI-Q never treats it as successful attestation.

OpenShell shared attachment remains available only as an explicit debug escape hatch:
`existing_sandbox_name` plus `allow_shared_sandbox: true`. It is not a job isolation boundary
and must not be used for mutually untrusted jobs. Production policy validation also requires
`landlock.compatibility: hard_requirement`; a local demo may explicitly set both the policy
and `require_hard_landlock: false` to accept `best_effort`.

The agent only ever sees a `read_file`/`write_file`/`edit_file`/`execute` tool surface
plus `/shared/` for durable text. Binary artifacts are harvested host-side via
`download_files` and referenced in reports as `artifact://<id>` (never base64).

## Module map

| File | Purpose |
|---|---|
| `base.py` | `SandboxProvider` ABC. Force only `execute` + `capabilities`; the base owns lazy single-flight creation, a serialization lock, idempotency-gated retry, `close()`, `terminate()`. |
| `registry.py` | `register_sandbox_provider` / `create_sandbox_backend` (config-driven dispatch + capability gate). |
| `config.py` | `SandboxConfig`: common fields + nested `providers.<name>` + `artifact_capture` + `lifecycle_scope`; legacy flat-config shim; provider validated against the registry. |
| `capabilities.py` | `SandboxCapabilities` + `verify_capabilities` (fail-closed: refuse to run if a required guarantee like `block_network` is unsupported). |
| `providers/modal.py` | Modal provider (cloud). Create-fresh semantics (no silent attach-by-name). |
| `providers/openshell.py` | OpenShell provider (enterprise/on-prem). Lazy, ad-hoc deps; per-job policy creation, readiness/revision attestation, and confined transfer. |
| `artifacts/models.py` | `Artifact` record (id, mime, sha256, size, provenance, status). Metadata only. |
| `artifacts/manifest.py` | `manifest.json` schema + parser. |
| `artifacts/store.py` | `SqlArtifactStore` coordinates SQL metadata with the configured byte provider. |
| `artifacts/blob_store.py` | Byte adapters for SQL BLOBs and S3-compatible object storage. |
| `artifacts/factory.py` | Builds the application store from `AIQ_ARTIFACT_*` environment variables. |
| `artifacts/manager.py` | Harvest pipeline: manifest-first + scan, path-traversal confinement, MIME-from-bytes, SVG sanitize, render-gate, quotas, dedup, store-then-emit, `artifact://` resolution. |

## Adding a provider (the whole surface)

```python
from deepagents.backends.sandbox import BaseSandbox
from ..base import SandboxProvider
from ..capabilities import SandboxCapabilities
from ..registry import register_sandbox_provider

class MySandboxProvider(SandboxProvider):
    provider_name = "mybox"

    @classmethod
    def _scoped_name(cls, job_id: str) -> str:
        return job_id                      # apply provider naming rules

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(supports_network_policy=True, supports_artifact_download=True)

    def is_recoverable_error(self, exc: Exception) -> bool:
        return False                       # classify stale/transient errors for retry

    def _create_session(self) -> BaseSandbox:
        # lazy-import your SDK; create/attach a job-scoped sandbox; return a BaseSandbox.
        ...

register_sandbox_provider("mybox", MySandboxProvider)
```

Add a `MyProviderConfig` sub-model to `SandboxProvidersConfig` in `config.py`. You do
NOT implement `read_file`/`write_file`/`ls`/`glob` (inherited from `BaseSandbox` on top
of `execute`) or the retry/lock/lifecycle (the base owns those). Every provider must
pass the compliance suite (`tests/.../sandbox/test_provider_compliance.py`).

### Out-of-tree providers (entry points)

Third-party packages contribute providers without editing AI-Q by declaring the
`aiq.sandbox_providers` entry-point group (the same plug-in pattern as NAT and
deepagents Code). They are discovered lazily on first registry use:

```toml
# in the third-party package's pyproject.toml
[project.entry-points."aiq.sandbox_providers"]
mybox = "my_pkg.provider:MySandboxProvider"
```

The entry-point name becomes the config `provider` key. A broken plugin is logged and
skipped — it can never break resolution of the built-in providers.

## Config (sandbox block)

```yaml
sandbox:
  enabled: true
  provider: openshell          # registry key
  workdir: /sandbox            # injected into prompts + skills
  network:                     # normalized, provider-neutral egress policy
    mode: allowlist            # blocked | allowlist | open  (legacy `block_network: true` => blocked)
    allow: [api.github.com, github.com]  # policy grants must be a subset of this list
  timeout: 1200
  idle_timeout: 1800
  resources:                   # optional CPU/memory caps; omit for no limit
    # cpu: 2                   # cores; needs supports_resource_limits (Modal enforces; OpenShell does not)
    # memory_mb: 4096          # a requested limit on a provider that can't enforce it fails closed
  artifact_capture:
    enabled: true              # requires supports_artifact_download
    max_file_bytes: 50000000
    allow_extensions: [.png, .jpg, .jpeg, .webp, .csv, .json, .md, .ipynb, .pdf]
  providers:
    modal:
      app_name: aiq-deep-research
      image: python:3.12-slim
      python_packages: [matplotlib, numpy, pandas, pillow, tabulate]
    openshell:
      gateway: null            # null = locally selected gateway
      image: aiq-openshell-demo:latest
      policy: configs/openshell/generated/aiq-openshell-policy.yaml
      delete_on_exit: true
      attest: true
      policy_load_timeout_seconds: 30
      cleanup_timeout_seconds: 30
      # expected_policy_version: 1
      require_hard_landlock: true
```

The legacy flat shape (top-level `app_name`/`image`/`python_packages`) still loads and
is lifted into `providers.modal`.

## Artifact runtime

- Generated code writes binaries + a `manifest.json` to `artifact_dir`.
- Successful `execute` calls trigger a manifest-only checkpoint. Terminal finalization runs
  one manifest + directory scan on success or failure. On cancellation, that scan runs only
  when the provider operation lease is immediately available; a busy sandbox is terminated
  immediately, while completed execute outputs remain preserved by earlier checkpoints.
- The `ArtifactManager` pulls bytes via `download_files`, runs the validation pipeline
  (path-traversal confinement -> extension allowlist -> size cap -> MIME-from-bytes/spoof
  reject -> quota -> SVG sanitize -> sha256), stores metadata in SQL and bytes through the
  configured artifact blob provider, then emits an
  `artifact.update` event (durable metadata + `content_url`, never bytes or URL-as-text).
- Reports reference artifacts as `![caption](artifact://<filename-or-id>)`; the report
  postprocessor rewrites filename refs to durable ids and drops unknown/foreign refs.
- Endpoints: `GET /v1/jobs/async/job/{job_id}/artifacts` and `.../artifacts/{id}/content`
  (auth-scoped via `authorize_job_access`). CLI: `python3 skills/aiq-research/scripts/aiq.py artifacts <job_id> [--download-dir DIR]`.
- Render gate: only PNG/JPEG/WebP may render inline; SVG/notebook/PDF are download-only.
- Transfer guards (artifacts come from an untrusted sandbox): the OpenShell download
  bootstrap fails closed BEFORE reading bytes - it rejects symlink escapes (`realpath`
  differs from the lexical path: leaf or parent), directories, and files over
  `max_file_bytes` - so a hostile sandbox cannot pull an out-of-tree or oversized file
  into host memory. The harvest also count-gates before each download and bounds the
  directory scan, and decoded bytes are base64-validated. SQL is fully parameterized
  and the content endpoint is auth-scoped per job with `nosniff` + RFC 5987 filenames.

### Report post-processing (host-side, in `agent.run`)

Run once after the report is produced, reusing a single artifact fetch:
- `resolve_report_references` - rewrite `artifact://<filename>` to `artifact://<id>`; drop unknown/foreign refs.
- `ensure_inline_artifacts_embedded` - append a `## Figures` section embedding any produced
  inline image the model forgot to reference (so a generated chart always surfaces).
- `append_artifact_index` - append a `## Generated Artifacts` list crediting every harvested
  file (charts and their backing CSVs), alongside the external `## Sources`.

### Rendering surfaces

The stored report keeps `artifact://<id>`; each surface resolves it at its own edge (one
shared helper, `MarkdownRenderer/artifact-url.ts`, builds the content path):
- **UI report**: `MarkdownRenderer` preserves the `artifact://` scheme via a custom
  `urlTransform` (react-markdown would otherwise blank a non-standard scheme), and an `img`
  renderer rewrites it to the same-origin `/api/jobs/async/job/{job_id}/artifacts/{id}/content`
  (the Next proxy streams bytes through). Job id comes from `selectResolvedDeepResearchJobId`.
- **PDF export**: `/api/generate-pdf` fetches each artifact server-side and inlines it as a
  `data:` URI (<= 8 MiB); `ReactPdfDocument` renders raster images as block figures (paragraphs
  and list items). Non-image refs are skipped.
- **Markdown download**: `artifact://` is rewritten to an absolute content URL so the `.md`
  renders while the backend is reachable.
- **Skill/CLI**: `aiq.py report <job_id> --out-dir DIR` writes `report.md` plus an
  `artifacts/` folder and rewrites links to local files (portable, renders offline).

## Providers

### Modal (cloud)

Requires `modal` + `langchain-modal` (in `pyproject`) and `modal setup`. See
`docs/source/examples/skills-sandbox/index.md`.

### OpenShell (experimental)

Each job creates a new policy-bound OpenShell sandbox and deletes it on terminal cleanup.
AI-Q refuses startup if the YAML does not match the installed SDK schema, the policy grants a
host or hostless/CIDR override outside the declared public network contract, production Landlock
mode is not fail-closed, or the gateway cannot prove the submitted policy is effective. The
creation spec deliberately has no copied host environment or credential providers.
Owned sandboxes carry `aiq=deep-research` and a normalized `aiq-job-id` in both OpenShell
gateway metadata and runtime template metadata so operators can use label selectors reliably.

Two ad-hoc deps (never in `pyproject`): the `openshell` SDK and the official
`langchain-nvidia-openshell` adapter (`OpenShellSandbox`), the OpenShell partner package in
[`langchain-ai/langchain-nvidia`](https://github.com/langchain-ai/langchain-nvidia/pull/303).
They remain lazy so selecting another provider does not install or import OpenShell.
The provider config supports per-job policy creation and an explicit shared-debug attachment;
policy-configured shared attachment is strictly attested, while policy-free attachment emits
`assurance=reduced`.

Use the canonical [OpenShell deployment guide](../../../../../docs/source/deployment/openshell.md)
for installation, platform support, authenticated gateway ownership, policy/config pairing,
startup, live acceptance, and troubleshooting. Operator commands are intentionally not
duplicated in this implementation reference.

Inference is routed host-side (e.g. NVIDIA Build or an internal inference hub set in the
config); sandbox policy egress never requires or receives the inference key.

**File-transfer gotcha:** the provider overrides file transfer with an env-free shim that
passes the path via `argv`. OpenShell 0.0.57-0.0.67 strip
`OPENSHELL_`-prefixed env before exec, so the adapter's env-based file transfer silently
fails (masked host-side as `permission_denied`). Set `AIQ_OPENSHELL_ADAPTER_FILE_TRANSFER=1`
to delegate uploads to the official adapter and validate the upstream argv fix
([langchain-nvidia#303](https://github.com/langchain-ai/langchain-nvidia/pull/303)). Downloads
always use AI-Q's bounded shim so realpath confinement and pre-transfer size checks remain
in force. Once the upstream adapter provides equivalent guards, drop the shim and toggle.

## Artifact byte storage

SQL BLOB storage remains the default when `AIQ_ARTIFACT_BLOB_PROVIDER` is unset or
set to `sql`. Production deployments can set it to `s3` to store bytes in AWS S3 or
an S3-compatible service while retaining artifact metadata in the job database.

AWS S3:

```bash
AIQ_ARTIFACT_BLOB_PROVIDER=s3
AIQ_ARTIFACT_S3_BUCKET=aiq-artifacts
AIQ_ARTIFACT_S3_REGION=us-west-2
AIQ_ARTIFACT_S3_PREFIX=artifacts/v1
```

MinIO or another S3-compatible service uses the same provider and additionally sets
the custom endpoint:

```bash
AIQ_ARTIFACT_BLOB_PROVIDER=s3
AIQ_ARTIFACT_S3_BUCKET=aiq-artifacts
AIQ_ARTIFACT_S3_ENDPOINT_URL=http://minio:9000
AIQ_ARTIFACT_S3_REGION=us-east-1
AIQ_ARTIFACT_S3_PREFIX=artifacts/v1
```

`AIQ_ARTIFACT_S3_BUCKET` is required for S3 storage. The endpoint is optional: leave
it unset for AWS S3 and set it for MinIO, Ceph, R2, or another compatible endpoint.
The region and prefix are optional; the prefix defaults to `artifacts/v1`. Credentials
come from workload identity, deployment secrets, or the standard AWS credential chain.
For local MinIO, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` can hold the local
MinIO credentials. Install the optional dependency with `uv sync --extra s3`.

Selecting `s3` does not automatically fall back to SQL if object storage fails. The selected
provider applies to the whole application. Artifact cleanup follows the retention period and
removes object bytes before SQL metadata.

Custom endpoints use path-style bucket addressing for MinIO compatibility.

## Operational knobs

- `AIQ_MAX_SANDBOXES_PER_PRINCIPAL` / `AIQ_MAX_SANDBOXES_GLOBAL` (default-off): submit-path
  concurrency/cost caps for sandbox-enabled jobs.
- `AIQ_OPENSHELL_ADAPTER_FILE_TRANSFER` (default-off): route OpenShell uploads through the
  official adapter instead of the env-free shim (see OpenShell gotcha above).
- Artifact retention reuses the existing periodic cleanup (`expiry_seconds`).
- In-container OpenShell log verbosity (opt-in): `agent.execute()` calls and their output are
  already logged on the AI-Q side (the `execute` tool-call events). To also see what runs
  inside the OpenShell container, rebuild the sandbox image with a higher `RUST_LOG`:
  `./scripts/openshell/setup_openshell.sh --sandbox-log-level debug` (or `--build-arg
  OPENSHELL_SANDBOX_LOG_LEVEL=debug`). Default `warn` keeps OpenShell's stock behavior.
  Read the generated sandbox name from AI-Q's attestation/cleanup events, then use
  `openshell logs <sandbox-name>`, the OpenShell TUI, or inside
  the sandbox at `/var/log/openshell.*.log` (e.g. `grep "OCSF PROC:"` for process activity).

## Testing

```bash
pytest tests/aiq_agent/agents/deep_researcher/sandbox/ -q
```

Core provider/artifact tests use fake SDK objects and run without a live Modal/OpenShell
gateway. The exact checked-policy/protobuf schema assertion is optional when the SDK is absent.
The opt-in gateway acceptance suite and its environment contract are documented in the
[OpenShell deployment guide](../../../../../docs/source/deployment/openshell.md#acceptance-tests).

## Troubleshooting

- **`Input tag 'tavily_web_search' ... does not match` / `Unknown field name front_end`**:
  the workspace plugin packages aren't installed. Install them (don't re-run `setup.sh`,
  which recreates `.venv`):
  `uv pip install -e ./frontends/aiq_api -e ./sources/tavily_web_search -e "./sources/knowledge_layer[llamaindex,foundational_rag]" -e ./sources/exa_web_search -e ./sources/google_scholar_paper_search`
- **OpenShell installation, gateway, policy, readiness, or cleanup failures**: follow the
  canonical [OpenShell troubleshooting contract](../../../../../docs/source/deployment/openshell.md#inspection-and-troubleshooting).
- **`network.mode` rejected at startup**: the selected provider doesn't declare the
  matching capability (`supports_network_policy` for `blocked`, `supports_network_allowlist`
  for `allowlist`). Choose a capable provider or relax `network.mode` (e.g. to `open`).
- **Chart shows as text / blank instead of an image in the report or PDF**: the stored
  report carries `artifact://<id>`; rendering needs all of (a) a resolved job id
  (`selectResolvedDeepResearchJobId`), (b) the `MarkdownRenderer` `urlTransform` preserving
  the `artifact://` scheme, and (c) for PDF, an explicit image width (react-pdf draws
  intrinsic pixel size otherwise, overflowing the page). Re-export after the dev server
  recompiles and check the `[PDF] inline:` lines on `/api/generate-pdf`. CSVs are not images
  and never embed as pictures - they appear in `## Generated Artifacts` and download links.
- **Job harvested 0 artifacts though the report describes a chart**: the model wrote a
  sandbox path as prose without embedding `![caption](artifact://<file>)`, or wrote outside
  `artifact_dir`. The skill mandates the embed token and writing to `artifact_dir`; the
  `final_harvest` scan + manifest union and `ensure_inline_artifacts_embedded` are the
  backstops. Confirm `artifact_dir` in the prompt matches `workdir`.
