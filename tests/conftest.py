# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Repository-wide pytest isolation for process-discovered configuration."""

import os
import shutil
import tempfile
from pathlib import Path

# NeMo Relay discovers ``$XDG_CONFIG_HOME/nemo-relay/plugins.toml`` during
# import/initialization. Unit tests create real Relay scopes, so inheriting a
# developer's XDG directory would export fixture traffic to their configured
# observability destinations. Set this during conftest import, before pytest
# imports test modules that import Relay.
_TEST_XDG_CONFIG_HOME = Path(tempfile.mkdtemp(prefix="aiq-pytest-xdg-"))
os.environ["XDG_CONFIG_HOME"] = str(_TEST_XDG_CONFIG_HOME)


def pytest_unconfigure() -> None:
    """Remove the process-local Relay discovery directory after the test run."""
    shutil.rmtree(_TEST_XDG_CONFIG_HOME, ignore_errors=True)
