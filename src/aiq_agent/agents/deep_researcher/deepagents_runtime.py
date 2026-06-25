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

"""DeepAgents skills and sandbox runtime support for deep research."""

from __future__ import annotations

import importlib.util
import logging
import re
import shlex
import threading
from pathlib import Path
from typing import Any
from typing import Literal
from uuid import uuid4

from deepagents.backends import CompositeBackend
from deepagents.backends import FilesystemBackend
from deepagents.backends import StateBackend
from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.protocol import FileDownloadResponse
from deepagents.backends.protocol import FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

BUILTIN_SKILLS_DIR = Path(__file__).with_name("skills")
BUILTIN_SKILL_SOURCE = "/skills/"
SHARED_ROUTE = "/shared/"
SKILL_AGENT_NAMES = frozenset({"researcher-agent", "writer-agent"})


class DeepResearchSkillsConfig(FunctionBaseConfig, name="deep_research_skills"):
    """AI-Q config surface for assigning built-in DeepAgents skill collections."""

    model_config = ConfigDict(extra="forbid")

    agents: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Per-agent built-in skill collection names keyed by DeepAgents agent name.",
    )
    require_sandbox: tuple[str, ...] = Field(
        default=(),
        description="Skill collection names that require a sandbox when assigned to any agent.",
    )

    @field_validator("agents")
    @classmethod
    def _validate_agent_names(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        unknown = sorted(set(value) - SKILL_AGENT_NAMES)
        if unknown:
            raise ValueError(
                f"Unknown deep research skill agent(s): {unknown}. Known agents: {sorted(SKILL_AGENT_NAMES)}"
            )
        return value


class DeepResearchSandboxConfig(FunctionBaseConfig, name="deep_research_sandbox"):
    """AI-Q config surface for the optional DeepAgents sandbox backend."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["modal"] = Field(default="modal", description="Sandbox backend provider.")
    app_name: str = Field(default="aiq-deep-research", description="Modal app name for deep research sandboxes")
    image: str = Field(default="python:3.13-slim", description="Container image for Modal sandboxes")
    packages: tuple[str, ...] = Field(
        default=(),
        description="Python packages to install into the Modal sandbox image.",
    )
    workdir: str = Field(default="/workspace", description="Working directory inside Modal sandboxes")
    timeout: int = Field(default=1200, description="Maximum Modal sandbox lifetime in seconds")
    idle_timeout: int = Field(default=1800, description="Modal sandbox idle timeout in seconds")
    network: Literal["blocked", "enabled"] = Field(
        default="blocked",
        description="Outbound network policy for Modal sandboxes.",
    )

    @property
    def block_network(self) -> bool:
        """Return the block_network flag for this public network setting."""
        return self.network == "blocked"


class DeepAgentsRuntime:
    """Build DeepAgents backend wiring and resolve AI-Q skill collections."""

    def __init__(
        self,
        *,
        skills: DeepResearchSkillsConfig | None = None,
        sandbox: DeepResearchSandboxConfig | None = None,
        job_id: str | None = None,
    ) -> None:
        self._skills = skills
        self._sandbox = sandbox
        self._job_id = str(job_id) if job_id is not None else str(uuid4())
        self._backend: Any | None = None
        self._skill_sources_by_agent = _resolve_agent_skill_sources(skills)
        self._skill_sources = tuple(
            dict.fromkeys(source for sources in self._skill_sources_by_agent.values() for source in sources)
        )
        _validate_sandbox_requirements(
            skills=skills,
            sandbox=sandbox,
        )

    @property
    def execution_enabled(self) -> bool:
        """Return true when the runtime has a sandbox backend for execute."""
        return self._sandbox is not None

    @property
    def skills_enabled(self) -> bool:
        """Return true when any agent has configured skill sources."""
        return bool(self._skill_sources)

    def skill_sources_for(self, agent_name: str) -> list[str] | None:
        """Return DeepAgents source paths for an agent/subagent name."""
        sources = self._skill_sources_by_agent.get(agent_name)
        return list(sources) if sources else None

    @property
    def backend(self) -> Any:
        """Return the concrete backend instance passed to DeepAgents."""
        if self._backend is None:
            self._backend = _build_backend(
                sandbox=self._sandbox,
                job_id=self._job_id,
                skills_enabled=self.skills_enabled,
            )
        return self._backend


def _build_backend(
    *,
    sandbox: DeepResearchSandboxConfig | None,
    job_id: str,
    skills_enabled: bool,
) -> Any:
    """Build the smallest stock DeepAgents backend needed for this run."""
    default = _create_sandbox_backend(sandbox, job_id) if sandbox is not None else StateBackend()
    routes: dict[str, Any] = {}
    if skills_enabled:
        routes[BUILTIN_SKILL_SOURCE] = _skills_backend()
    if sandbox is not None:
        routes[SHARED_ROUTE] = StateBackend()
    if not routes:
        return default
    return CompositeBackend(default=default, routes=routes)


def _skills_backend() -> FilesystemBackend:
    """Return the filesystem-backed built-in skills route."""
    return FilesystemBackend(root_dir=BUILTIN_SKILLS_DIR.resolve(), virtual_mode=True)


def discover_skill_collections(root: Path = BUILTIN_SKILLS_DIR) -> dict[str, str]:
    """Return built-in skill collection names mapped to DeepAgents source paths."""
    if not root.exists():
        return {}

    collections: dict[str, str] = {}
    for skill_file in sorted(root.glob("**/SKILL.md")):
        collection_dir = skill_file.parent.parent
        if collection_dir == root:
            continue
        name = collection_dir.relative_to(root).as_posix()
        collections[name] = f"{BUILTIN_SKILL_SOURCE}{name}/"
    return collections


def resolve_skill_collections(collection_names: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve public skill collection names to DeepAgents source paths."""
    known = discover_skill_collections()
    unknown = sorted(set(collection_names) - set(known))
    if unknown:
        raise ValueError(f"Unknown deep research skill collection(s): {unknown}. Known collections: {sorted(known)}")
    return tuple(known[name] for name in collection_names)


def _resolve_agent_skill_sources(skills: DeepResearchSkillsConfig | None) -> dict[str, tuple[str, ...]]:
    if skills is None:
        return {}
    return {
        agent_name: resolve_skill_collections(collection_names)
        for agent_name, collection_names in skills.agents.items()
        if collection_names
    }


def _validate_sandbox_requirements(
    *,
    skills: DeepResearchSkillsConfig | None,
    sandbox: DeepResearchSandboxConfig | None,
) -> None:
    if skills is None or not skills.require_sandbox:
        return

    resolve_skill_collections(skills.require_sandbox)
    if sandbox is not None:
        return

    required_collections = set(skills.require_sandbox)
    violating_agents = sorted(
        agent_name
        for agent_name, collections in skills.agents.items()
        if required_collections.intersection(collections)
    )
    if violating_agents:
        raise ValueError(
            "Deep research skill collection(s) require a sandbox for agent(s) "
            f"{violating_agents}: {sorted(skills.require_sandbox)}. Configure sandbox or remove the collection(s)."
        )


def _validate_modal_sandbox_name(job_id: str) -> str:
    if len(job_id) > 64 or re.match(r"^[a-zA-Z0-9-_.]+$", job_id) is None or re.match(r"^ap-[a-zA-Z0-9]{22}$", job_id):
        raise ValueError(
            "Deep research job_id must be a valid Modal sandbox name: "
            "64 characters or fewer, using only alphanumeric characters, dashes, periods, and underscores."
        )
    return job_id


def _create_sandbox_backend(config: DeepResearchSandboxConfig, job_id: str) -> Any:
    if config.provider == "modal":
        return _create_modal_backend(config, job_id)
    raise ValueError(f"Unsupported sandbox provider: {config.provider}. Supported providers: modal")


def _create_modal_backend(config: DeepResearchSandboxConfig, job_id: str) -> Any:
    _ensure_modal_dependencies()
    return _LazyModalSandboxBackend(config, job_id)


def _ensure_modal_dependencies() -> None:
    missing = [
        package
        for module_name, package in (("modal", "modal"), ("langchain_modal", "langchain-modal"))
        if importlib.util.find_spec(module_name) is None
    ]
    if missing:
        packages = ", ".join(missing)
        raise ImportError(
            "Modal sandbox is configured, but required package(s) are missing: "
            f"{packages}. Install the Modal sandbox dependencies or remove the sandbox config."
        )


class _LazyModalSandboxBackend(BaseSandbox):
    """Job-scoped Modal backend that creates and recreates the sandbox on demand."""

    def __init__(self, config: DeepResearchSandboxConfig, job_id: str) -> None:
        self.config = config
        self.sandbox_name = _validate_modal_sandbox_name(job_id)
        self._backend: Any | None = None
        self._lock = threading.Lock()

    @property
    def id(self) -> str:
        backend = self._backend
        if backend is None:
            return self.sandbox_name
        return backend.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        for attempt in range(2):
            try:
                return self._get_backend().execute(command, timeout=timeout)
            except Exception as exc:
                if attempt == 0 and _is_modal_not_found_error(exc):
                    logger.warning(
                        "Modal sandbox %s disappeared during execute; recreating and retrying once",
                        self.sandbox_name,
                    )
                    self._reset_backend()
                    continue
                raise
        raise RuntimeError("unreachable")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        for attempt in range(2):
            try:
                return self._get_backend().upload_files(files)
            except Exception as exc:
                if attempt == 0 and _is_modal_not_found_error(exc):
                    logger.warning(
                        "Modal sandbox %s disappeared during file upload; recreating and retrying once",
                        self.sandbox_name,
                    )
                    self._reset_backend()
                    continue
                raise
        raise RuntimeError("unreachable")

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        for attempt in range(2):
            try:
                return self._get_backend().download_files(paths)
            except Exception as exc:
                if attempt == 0 and _is_modal_not_found_error(exc):
                    logger.warning(
                        "Modal sandbox %s disappeared during file download; recreating and retrying once",
                        self.sandbox_name,
                    )
                    self._reset_backend()
                    continue
                raise
        raise RuntimeError("unreachable")

    def _get_backend(self) -> Any:
        backend = self._backend
        if backend is not None:
            return backend

        with self._lock:
            if self._backend is None:
                logger.info(
                    "Modal sandbox backend init: sandbox_name=%s app=%s",
                    self.sandbox_name,
                    self.config.app_name,
                )
                self._backend = _create_modal_backend_now(self.config, self.sandbox_name)
            return self._backend

    def _reset_backend(self) -> None:
        with self._lock:
            logger.warning(
                "Modal sandbox backend RESET: sandbox_name=%s app=%s "
                "(any uploaded files in the previous sandbox are now lost)",
                self.sandbox_name,
                self.config.app_name,
            )
            self._backend = _create_modal_backend_now(self.config, self.sandbox_name, force_new=True)


def _create_modal_backend_now(
    config: DeepResearchSandboxConfig,
    sandbox_name: str,
    *,
    force_new: bool = False,
) -> Any:
    try:
        import modal
        from langchain_modal import ModalSandbox
    except ImportError as exc:
        raise ImportError(
            "The Modal sandbox backend requires the `langchain-modal` and `modal` packages. "
            "Install the updated AIQ dependencies and run `modal setup` before enabling a Modal sandbox."
        ) from exc

    app = modal.App.lookup(name=config.app_name, create_if_missing=True)
    if not force_new:
        try:
            sandbox = modal.Sandbox.from_name(config.app_name, sandbox_name)
            logger.info("Modal sandbox attached to existing instance: name=%s", sandbox_name)
            return ModalSandbox(sandbox=sandbox)
        except modal.exception.NotFoundError:
            logger.info("Modal sandbox not found, creating fresh instance: name=%s", sandbox_name)

    image = modal.Image.from_registry(config.image)
    if config.packages:
        image = image.pip_install(*config.packages)
    if config.workdir:
        image = image.run_commands(f"mkdir -p {shlex.quote(config.workdir)}")

    try:
        sandbox = modal.Sandbox.create(
            app=app,
            image=image,
            workdir=config.workdir,
            name=sandbox_name,
            timeout=config.timeout,
            idle_timeout=config.idle_timeout,
            block_network=config.block_network,
        )
        logger.info(
            "Modal sandbox CREATED: name=%s image=%s workdir=%s timeout=%ds",
            sandbox_name,
            config.image,
            config.workdir,
            config.timeout,
        )
    except modal.exception.AlreadyExistsError:
        sandbox = modal.Sandbox.from_name(config.app_name, sandbox_name)
        logger.info("Modal sandbox attached after AlreadyExistsError: name=%s", sandbox_name)
    return ModalSandbox(sandbox=sandbox)


def _is_modal_not_found_error(exc: Exception) -> bool:
    try:
        import modal

        return isinstance(exc, modal.exception.NotFoundError)
    except ImportError:
        return exc.__class__.__name__ == "NotFoundError" and exc.__class__.__module__.startswith("modal")
