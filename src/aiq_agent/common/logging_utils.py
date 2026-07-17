# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Helpers for logging stable references without exposing opaque identifiers."""

import hashlib


def log_identifier_ref(identifier: str) -> str:
    """Return a stable correlation reference that does not reveal ``identifier``."""
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"
