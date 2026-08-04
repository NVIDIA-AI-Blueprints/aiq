# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Non-sensitive helpers for GSF result provenance."""

import hashlib


def sql_sha256(sql: str) -> str:
    """Return a stable SQL digest without logging or persisting the SQL text."""

    return hashlib.sha256(sql.encode("utf-8")).hexdigest()
