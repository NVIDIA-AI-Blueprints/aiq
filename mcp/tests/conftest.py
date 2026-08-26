# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Keep pytest importlib collection from treating the component folder as the MCP package."""

import importlib
import sys
from pathlib import Path

# Pytest derives importlib-mode test module names from their repository path.
# For tests below a top-level mcp directory it can pre-create a namespace
# module named mcp before test collection, hiding the installed protocol
# package. Replace only that collection-only namespace with the dependency.
protocol_package = sys.modules.get("mcp")
protocol_paths = getattr(protocol_package, "__path__", ())
if not any((Path(path) / "server").is_dir() for path in protocol_paths):
    sys.modules.pop("mcp", None)
importlib.import_module("mcp.server.fastmcp")
