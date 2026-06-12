# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
"""Repo-local agent skills under .agents/skills must pass the skill validator.

This guards the maintainer skill set in CI's pytest job, in addition to the
pre-commit hook, since the skills-eval workflow is scoped to skills/ only.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / ".agents" / "skills"
VALIDATOR = REPO_ROOT / "scripts" / "validate_skills.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_skills", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve annotations under
    # `from __future__ import annotations` during dynamic import.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_agent_skills_are_valid():
    validator = _load_validator()
    report = validator.validate_roots([SKILLS_ROOT])
    assert report.skills_checked >= 1, f"no skills found under {SKILLS_ROOT}"
    assert report.errors == [], "skill validation errors:\n" + "\n".join(report.errors)
