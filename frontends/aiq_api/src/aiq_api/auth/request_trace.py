# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

_current_request_trace_tags: ContextVar[dict[str, str]] = ContextVar("_current_request_trace_tags", default={})


def get_request_trace_tags() -> dict[str, str]:
    """Return the trace tags resolved for the current request."""
    return _current_request_trace_tags.get()


@contextmanager
def request_trace_tag_context(tags: dict[str, str]):
    """Bind request trace tags while NAT emits spans for this request."""
    token = _current_request_trace_tags.set(dict(tags))
    try:
        yield
    finally:
        _current_request_trace_tags.reset(token)


def _inject_request_trace_attributes(span) -> None:
    tags = get_request_trace_tags()
    if not tags:
        return

    for key, value in tags.items():
        prefixed_key = key if key.startswith("nat.") else f"nat.{key}"
        try:
            span.set_attribute(prefixed_key, value)
        except Exception:
            logger.debug("Failed to inject request trace tag %s onto NAT span", prefixed_key, exc_info=True)


def install_request_trace_span_injection() -> None:
    """Patch NAT's span exporter so exported spans inherit request trace attributes."""
    from nat.observability.exporter.span_exporter import SpanExporter

    process_start_event = SpanExporter._process_start_event
    if getattr(process_start_event, "__aiq_request_trace_patched__", False):
        return

    def patched_process_start_event(self, event) -> None:
        process_start_event(self, event)
        tags = get_request_trace_tags()
        if not tags:
            return

        try:
            span = self._outstanding_spans.get(event.UUID)
        except Exception:
            logger.debug("Failed to look up NAT span for request trace tags", exc_info=True)
            return
        if span is None:
            logger.debug("No NAT span found for request trace tag injection: %s", event.UUID)
            return

        _inject_request_trace_attributes(span)

    patched_process_start_event.__aiq_request_trace_patched__ = True
    SpanExporter._process_start_event = patched_process_start_event
    logger.info("Installed NAT request trace span attribute injection")
