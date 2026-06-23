# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Built-in sandbox providers.

Importing this package registers the built-in providers with the registry. Each
provider self-registers at import; adding a new provider is one new module here.
"""

from __future__ import annotations

from .modal import ModalSandboxProvider
from .openshell import OpenShellSandboxProvider

__all__ = [
    "ModalSandboxProvider",
    "OpenShellSandboxProvider",
]
