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

"""Agent-local prompt loading utilities.

This module provides utilities for loading prompts co-located with agents.
Each agent package has a prompts/ directory containing its Jinja2 templates.
"""

import logging
from pathlib import Path
from typing import Any

import jinja2

logger = logging.getLogger(__name__)

_prompt_directories: list[tuple[int, Path]] = []


def register_prompt_directory(directory: Path, priority: int = 0) -> None:
    """Register an additional prompt search directory.

    Registered directories are checked in priority order (highest first)
    before the agent's own prompts/ directory. The directory should contain
    subdirectories matching agent names (e.g., ``deep_researcher/``,
    ``clarifier/``) with prompt files inside.

    Example layout::

        my_prompts/
        ├── deep_researcher/
        │   └── researcher.j2
        └── shallow_researcher/
            └── researcher.j2

    Usage::

        register_prompt_directory(Path("my_prompts"), priority=10)

    Args:
        directory: Path to the prompt override directory.
        priority: Higher priority directories are checked first. Default: 0.
    """
    _prompt_directories.append((priority, directory))
    _prompt_directories.sort(key=lambda x: x[0], reverse=True)
    logger.debug("Registered prompt directory: %s (priority=%d)", directory, priority)


def clear_prompt_directories() -> None:
    """Remove all registered prompt directories. Useful for testing."""
    _prompt_directories.clear()


class PromptError(Exception):
    """Error loading or rendering prompts."""

    pass


def load_prompt(path: Path, name: str) -> str:
    """
    Load a prompt template from an agent's prompts/ directory.

    Checks registered override directories first (highest priority first),
    then falls back to the agent's own prompts/ directory.

    Override directories should contain subdirectories matching agent names.
    For example, if an agent at ``agents/deep_researcher/`` calls
    ``load_prompt(AGENT_DIR / "prompts", "researcher")``, the loader checks
    each registered directory for ``<dir>/deep_researcher/researcher.j2``
    before falling back to the agent's own ``prompts/researcher.j2``.

    Args:
        path: Path to the agent's prompts directory.
        name: Name of the prompt file (e.g., 'system' or 'system.j2').

    Returns:
        The prompt template as a string.

    Raises:
        PromptError: If the prompt file cannot be found in any location.
    """
    # Determine agent name from path (path is typically AGENT_DIR / "prompts")
    agent_name = path.parent.name

    # Check registered override directories first
    for _priority, override_dir in _prompt_directories:
        override_path = _resolve_prompt_path(override_dir / agent_name, name)
        if override_path is not None:
            try:
                logger.debug("Using prompt override: %s", override_path)
                return override_path.read_text()
            except Exception as e:
                raise PromptError(f"Failed to load prompt override {override_path}: {e}") from e

    # Fall back to agent's own prompts directory
    prompt_path = _resolve_prompt_path(path, name)
    if prompt_path is None:
        raise PromptError(f"Prompt file not found: {name} in {path}")

    try:
        return prompt_path.read_text()
    except Exception as e:
        raise PromptError(f"Failed to load prompt {name}: {e}") from e


def _resolve_prompt_path(directory: Path, name: str) -> Path | None:
    """Resolve a prompt file path, trying exact name then .j2 extension.

    Returns:
        The resolved Path if the file exists, otherwise None.
    """
    prompt_path = directory / name
    if prompt_path.exists():
        return prompt_path
    if not name.endswith(".j2"):
        prompt_path = directory / f"{name}.j2"
        if prompt_path.exists():
            return prompt_path
    return None


def render_prompt_template(template: str, **kwargs: Any) -> str:
    """
    Render a Jinja2 template with the given variables.

    Args:
        template: The template string.
        **kwargs: Variables to substitute in the template.

    Returns:
        The rendered template.

    Raises:
        PromptError: If template rendering fails.
    """
    try:
        jinja_template = jinja2.Template(template, undefined=jinja2.StrictUndefined)
        return jinja_template.render(**kwargs)
    except jinja2.TemplateError as e:
        raise PromptError(f"Failed to render template: {e}") from e
