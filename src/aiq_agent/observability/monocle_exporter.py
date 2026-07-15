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

"""Optional Monocle observability for AI-Q.

Monocle (``monocle_apptrace``) instruments supported frameworks (LangChain,
LangGraph, etc.) in place and manages its own OpenTelemetry pipeline. It is not
a hard dependency of AI-Q: it activates only when a user opts in, and only if
``monocle_apptrace`` is installed (``uv sync --extra monocle``).

There are two opt-in paths, both funnelling through :func:`_setup_monocle_once`
so Monocle initializes at most once per process:

* **NAT telemetry exporter (canonical).** Add a ``monocle`` exporter under
  ``general.telemetry.tracing`` in the workflow YAML. This is the NAT-idiomatic
  mechanism; the exporter is built (and Monocle initialized) only when the
  workflow that references it is loaded.
* **Environment gate (deer-flow-style).** Set ``MONOCLE_TRACING=true`` and the
  CLI initializes Monocle at startup via :func:`setup_monocle_tracing_if_enabled`,
  reading ``MONOCLE_EXPORTERS`` / ``OKAHU_API_KEY``. Handy for enabling tracing
  without editing the config.

Precedence: the env gate runs at CLI startup, before the workflow (and thus any
YAML ``monocle`` exporter) is built, so when both are set the env gate wins and
the YAML exporter finds Monocle already initialized and does nothing further. To
drive the exporter list purely from YAML, leave ``MONOCLE_TRACING`` unset.

When neither path is taken, this module registers a config type with the NAT
registry but never imports ``monocle_apptrace`` -- default behavior is unchanged.
"""

import logging
import os

from pydantic import Field

from nat.builder.builder import Builder
from nat.cli.register_workflow import register_telemetry_exporter
from nat.data_models.telemetry_exporter import TelemetryExporterBaseConfig
from nat.observability.exporter.base_exporter import BaseExporter

logger = logging.getLogger(__name__)

# Default workflow name stamped onto Monocle spans.
_DEFAULT_WORKFLOW_NAME = "nvidia-aiq"

# Manual mirror of monocle_apptrace's supported exporters, kept local so a typo
# fails fast with a clear message instead of an opaque upstream error. Update
# this tuple when a monocle_apptrace bump adds or renames an exporter.
_MONOCLE_EXPORTERS = ("file", "console", "okahu", "s3", "blob", "gcs")

_TRUTHY_VALUES = {"1", "true", "yes", "on"}

# Guard so global Monocle instrumentation is initialized at most once per process,
# regardless of which opt-in path fires first.
_MONOCLE_INITIALIZED = False


def _env_flag(name: str) -> bool:
    """Whether env var ``name`` is set to a truthy value."""
    value = os.environ.get(name)
    return bool(value) and value.strip().lower() in _TRUTHY_VALUES


def _parse_exporters(exporters: str) -> list[str]:
    """Split a comma-separated exporter string, dropping blanks."""
    return [e.strip() for e in exporters.split(",") if e.strip()]


def _resolve_exporters(exporter_list: list[str], okahu_api_key: str | None) -> list[str]:
    """Validate and return the effective exporter list.

    An unknown exporter is a config typo, so it still fails fast with an actionable
    ``ValueError`` before any instrumentation runs. A missing secret, however, must
    degrade gracefully: when ``okahu`` is selected without ``OKAHU_API_KEY`` it is
    dropped (with a warning) and the remaining exporters continue. The returned list
    may be empty, in which case the caller skips Monocle cleanly rather than crashing.
    """
    unknown = [e for e in exporter_list if e not in _MONOCLE_EXPORTERS]
    if unknown:
        raise ValueError(
            f"MONOCLE_EXPORTERS has unknown exporter(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(_MONOCLE_EXPORTERS)}."
        )
    if "okahu" in exporter_list and not okahu_api_key:
        logger.warning(
            "Monocle 'okahu' exporter is selected but OKAHU_API_KEY is not set; "
            "skipping the okahu exporter and continuing with the remaining exporters."
        )
        exporter_list = [e for e in exporter_list if e != "okahu"]
    return exporter_list


def _warn_off_box(exporter_list: list[str]) -> None:
    """Warn when trace payloads will leave local disk via a remote exporter.

    Applied to both opt-in paths so a YAML-configured off-box exporter is no less
    visible than the env-gated one.
    """
    off_box = [e for e in exporter_list if e not in ("file", "console")]
    if off_box:
        logger.warning(
            "Monocle is exporting trace data (prompts, tool inputs/outputs, completions) beyond the local "
            ".monocle/ directory via: %s. Make sure that destination is trusted.",
            ", ".join(off_box),
        )


def flush_monocle_if_enabled() -> None:
    """Force-flush pending Monocle/OpenTelemetry spans; a no-op if Monocle was never set up.

    Call this before a hard process exit (e.g. ``os._exit``) so pending spans that the
    batch span processor has not yet exported are not silently dropped.
    """
    if not _MONOCLE_INITIALIZED:
        return
    try:
        from opentelemetry import trace

        force_flush = getattr(trace.get_tracer_provider(), "force_flush", None)
        if callable(force_flush):
            force_flush()
    except Exception:  # pragma: no cover - best-effort flush during shutdown
        logger.debug("Monocle span flush on exit failed.", exc_info=True)


def _setup_monocle_once(workflow_name: str, exporters: str) -> None:
    """Initialize Monocle telemetry once per process.

    Imports ``monocle_apptrace`` lazily and raises a clear ``RuntimeError`` with
    the install hint when the optional dependency is missing. ``exporters`` is a
    comma-separated string passed to ``monocle_exporters_list`` as-is.
    """
    global _MONOCLE_INITIALIZED
    if _MONOCLE_INITIALIZED:
        return

    try:
        from monocle_apptrace import setup_monocle_telemetry
    except ImportError as exc:
        raise RuntimeError(
            "Monocle observability is enabled but the optional 'monocle_apptrace' package is not installed. "
            "Install the 'monocle' extra: `uv sync --extra monocle` (or `pip install 'aiq-agent[monocle]'`)."
        ) from exc

    setup_monocle_telemetry(workflow_name=workflow_name, monocle_exporters_list=exporters or None)
    _MONOCLE_INITIALIZED = True
    logger.info(
        "Monocle telemetry initialized (workflow_name=%s, exporters=%s).",
        workflow_name,
        exporters or "<from environment>",
    )


def setup_monocle_tracing_if_enabled(workflow_name: str = _DEFAULT_WORKFLOW_NAME) -> bool:
    """Initialize Monocle from the environment when ``MONOCLE_TRACING`` is truthy.

    Mirrors the env surface documented across the sibling demos:

    * ``MONOCLE_TRACING`` -- truthy gate, off by default.
    * ``MONOCLE_EXPORTERS`` -- comma-separated exporter list, default ``file``.
    * ``OKAHU_API_KEY`` -- required only when the ``okahu`` exporter is selected.

    A no-op returning ``False`` when the gate is off. Called from the CLI startup
    so embedded/other entry points can call it themselves. Validates before
    instrumenting; a bad value raises ``ValueError``.
    """
    if not _env_flag("MONOCLE_TRACING"):
        return False

    exporters = (os.environ.get("MONOCLE_EXPORTERS") or "file").strip() or "file"
    exporter_list = _resolve_exporters(_parse_exporters(exporters), os.environ.get("OKAHU_API_KEY"))
    if not exporter_list:
        logger.warning("MONOCLE_TRACING is enabled but no usable exporters remain; skipping Monocle.")
        return False
    _warn_off_box(exporter_list)
    _setup_monocle_once(workflow_name=workflow_name, exporters=",".join(exporter_list))
    return True


def ensure_registered() -> None:
    """Import side effect: registers the ``monocle`` telemetry exporter config type.

    Importing this module runs the ``@register_telemetry_exporter`` decorator
    below, which is all that is needed for ``_type: monocle`` to be resolvable in
    workflow config. Kept as an explicit no-op call to mirror the sibling
    ``otel_header_redaction_exporter`` registration idiom.
    """
    return None


class MonocleTelemetryExporter(TelemetryExporterBaseConfig, name="monocle"):
    """Optional Monocle observability backend.

    Enable by adding this exporter under ``general.telemetry.tracing`` in a
    workflow config. Requires the ``monocle`` optional dependency to be
    installed; if it is missing, building the exporter raises a clear error
    instead of failing at import time.
    """

    workflow_name: str = Field(
        default=_DEFAULT_WORKFLOW_NAME,
        description="Workflow name Monocle stamps onto emitted spans.",
    )
    exporters: str = Field(
        # Defaults to the same MONOCLE_EXPORTERS env var the CLI env gate reads,
        # so the two opt-in paths agree; falls back to 'file'.
        default_factory=lambda: (os.environ.get("MONOCLE_EXPORTERS") or "file").strip() or "file",
        description="Comma-separated Monocle exporters (passed as monocle_exporters_list), "
        "e.g. 'file', 'okahu', or 'file,okahu'. Validated against: " + ", ".join(_MONOCLE_EXPORTERS) + ".",
    )


class _MonocleInstrumentationExporter(BaseExporter):
    """No-op NAT exporter that represents the Monocle instrumentation lifecycle.

    Monocle exports spans through its own pipeline, so this exporter does not
    consume NAT intermediate steps. It exists so Monocle initialization is tied
    to NAT's telemetry-exporter lifecycle (built only when configured).
    """

    def export(self, event) -> None:  # noqa: D102 - inherited semantics; intentionally a no-op
        return None


@register_telemetry_exporter(config_type=MonocleTelemetryExporter)
async def monocle_telemetry_exporter(config: MonocleTelemetryExporter, _builder: Builder):
    """Initialize Monocle telemetry when the ``monocle`` exporter is configured."""
    # If the env gate (or a prior workflow load) already initialized Monocle, the YAML
    # settings are documented as a no-op — return the exporter without re-validating.
    if _MONOCLE_INITIALIZED:
        yield _MonocleInstrumentationExporter()
        return
    # OKAHU_API_KEY is always sourced from the environment, matching the env gate.
    exporter_list = _resolve_exporters(_parse_exporters(config.exporters), os.environ.get("OKAHU_API_KEY"))
    if exporter_list:
        _warn_off_box(exporter_list)
        _setup_monocle_once(workflow_name=config.workflow_name, exporters=",".join(exporter_list))
    else:
        logger.warning("Monocle exporter configured but no usable exporters remain; skipping Monocle.")
    yield _MonocleInstrumentationExporter()
