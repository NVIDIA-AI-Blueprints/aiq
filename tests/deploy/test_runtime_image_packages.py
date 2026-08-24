# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runtime packaging checks for source plugins."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tavily_web_fetch_is_installed_in_runtime_image_and_dev_setup():
    """The plugin must be installed so NAT can discover its entry point."""
    assert "./sources/tavily_web_fetch" in (REPO_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "./sources/tavily_web_fetch" in (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
