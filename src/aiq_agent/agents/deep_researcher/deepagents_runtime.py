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

import logging
import re
import shlex
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from deepagents.backends import CompositeBackend
from deepagents.backends import StateBackend
from deepagents.backends.protocol import EditResult
from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.protocol import FileDownloadResponse
from deepagents.backends.protocol import FileUploadResponse
from deepagents.backends.protocol import ReadResult
from deepagents.backends.protocol import WriteResult
from deepagents.backends.sandbox import BaseSandbox
from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).parent
BUILTIN_SKILLS_DIR = AGENT_DIR / "skills"
BUILTIN_SKILL_SOURCE = "/skills/"
SHARED_ROUTE = "/shared/"


class _PrefixedStateBackend(StateBackend):
    """StateBackend that re-prepends a route prefix on error messages.

    Why: deepagents' CompositeBackend strips the route prefix before delegating
    to the routed backend, then rewrites WriteResult.path back to the full path
    on success — but does NOT rewrite the path embedded in WriteResult.error /
    EditResult.error. The agent then sees an error referencing a path it never
    wrote to (e.g. ``/0_weather_data.txt`` instead of ``/shared/0_weather_data.txt``)
    and chases the phantom path via shell, which routes to a different backend.
    Restore the user-visible path here so error messages are consistent with
    what the agent actually invoked.
    """

    def __init__(self, route_prefix: str) -> None:
        super().__init__()
        self._prefix = route_prefix.rstrip("/")

    def _restore(self, key: str) -> str:
        if key.startswith("/"):
            return f"{self._prefix}{key}"
        return f"{self._prefix}/{key}"

    def _rewrite_error(self, error: str, file_path: str) -> str:
        return error.replace(file_path, self._restore(file_path))

    def write(self, file_path: str, content: str) -> WriteResult:
        result = super().write(file_path, content)
        if result.error and file_path in result.error:
            return WriteResult(error=self._rewrite_error(result.error, file_path))
        return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        result = super().edit(file_path, old_string, new_string, replace_all=replace_all)
        if result.error and file_path in result.error:
            return EditResult(error=self._rewrite_error(result.error, file_path))
        return result

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        result = super().read(file_path, offset=offset, limit=limit)
        if result.error and file_path in result.error:
            return ReadResult(error=self._rewrite_error(result.error, file_path))
        return result


class SkillsConfig(BaseModel):
    """Configuration for built-in DeepAgents skills."""

    enabled: bool = Field(default=False, description="Enable DeepAgents skills for the orchestrator")
    sources: tuple[str, ...] = Field(
        default=(BUILTIN_SKILL_SOURCE,),
        description="DeepAgents skill source paths. Defaults to the built-in deep researcher skills directory.",
    )

    @classmethod
    def enabled_builtin(cls) -> SkillsConfig:
        return cls(enabled=True)


class SandboxConfig(BaseModel):
    """Configuration for a DeepAgents sandbox backend."""

    provider: str = Field(default="modal", description="Sandbox backend provider. Supported value: modal.")
    app_name: str = Field(default="aiq-deep-research", description="Modal app name for deep research sandboxes")
    image: str = Field(default="python:3.12-slim", description="Container image for Modal sandboxes")
    python_packages: tuple[str, ...] = Field(
        default=(),
        description="Python packages to install into the Modal sandbox image, such as matplotlib or pillow.",
    )
    workdir: str = Field(default="/workspace", description="Working directory inside Modal sandboxes")
    timeout: int = Field(default=1200, description="Maximum Modal sandbox lifetime in seconds")
    idle_timeout: int = Field(default=1800, description="Modal sandbox idle timeout in seconds")
    block_network: bool = Field(default=True, description="Block outbound network access from Modal sandboxes")

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        provider = self.provider.lower()
        if provider not in {"modal"}:
            raise ValueError(f"Unsupported sandbox provider: {self.provider}. Supported providers: modal")
        self.provider = provider


class DeepAgentsRuntime:
    """Builds DeepAgents backend kwargs and prepares built-in skill files."""

    def __init__(
        self,
        *,
        skills: SkillsConfig | None = None,
        sandbox: SandboxConfig | None = None,
        job_id: str | None = None,
    ) -> None:
        self.skills = skills or SkillsConfig()
        self.sandbox = sandbox
        self.job_id = str(job_id) if job_id is not None else str(uuid4())
        self._backend: Any | None = None

    @property
    def skill_sources(self) -> list[str] | None:
        if not self.skills.enabled:
            return None
        return list(self.skills.sources)

    @property
    def builtin_skills_dir(self) -> Path:
        return BUILTIN_SKILLS_DIR

    @property
    def create_agent_kwargs(self) -> dict[str, Any]:
        backend = self.backend
        kwargs: dict[str, Any] = {"backend": backend}
        if self.skill_sources is not None:
            kwargs["skills"] = self.skill_sources
        return kwargs

    @property
    def backend(self) -> Any:
        """Return the concrete backend instance passed to DeepAgents."""
        if self._backend is not None:
            return self._backend

        sandbox = self.sandbox
        if sandbox is not None:
            sandbox_backend = _create_sandbox_backend(sandbox, self.job_id)
            self._backend = CompositeBackend(
                default=sandbox_backend,
                routes={
                    BUILTIN_SKILL_SOURCE: _PrefixedStateBackend(BUILTIN_SKILL_SOURCE),
                    SHARED_ROUTE: _PrefixedStateBackend(SHARED_ROUTE),
                },
            )
            return self._backend

        self._backend = CompositeBackend(
            default=StateBackend(),
            routes={
                BUILTIN_SKILL_SOURCE: _PrefixedStateBackend(BUILTIN_SKILL_SOURCE),
                SHARED_ROUTE: _PrefixedStateBackend(SHARED_ROUTE),
            },
        )
        return self._backend

    def prepare_state(self, state: Any) -> Any:
        """Preload built-in skills into state when using the StateBackend."""
        if not self.skills.enabled:
            return state

        files = dict(getattr(state, "files", None) or {})
        skill_files = _builtin_skill_state_files()
        for file_path, file_data in skill_files.items():
            files.setdefault(file_path, file_data)
        return state.model_copy(update={"files": files})


def _collect_builtin_skill_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    if not BUILTIN_SKILLS_DIR.exists():
        return files

    for skill_dir in sorted(BUILTIN_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith(".") or skill_dir.name == "__pycache__":
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        files.append((f"{BUILTIN_SKILL_SOURCE}{skill_dir.name}/SKILL.md", skill_md.read_bytes()))
    return files


def _builtin_skill_state_files() -> dict[str, dict[str, str]]:
    timestamp = datetime.now().isoformat()
    return {
        _strip_builtin_skill_source(file_path): {
            "content": content.decode("utf-8"),
            "encoding": "utf-8",
            "created_at": timestamp,
            "modified_at": timestamp,
        }
        for file_path, content in _collect_builtin_skill_files()
    }


def _strip_builtin_skill_source(file_path: str) -> str:
    if file_path.startswith(BUILTIN_SKILL_SOURCE):
        return "/" + file_path[len(BUILTIN_SKILL_SOURCE) :].lstrip("/")
    return file_path


def _validate_modal_sandbox_name(job_id: str) -> str:
    if len(job_id) > 64 or re.match(r"^[a-zA-Z0-9-_.]+$", job_id) is None or re.match(r"^ap-[a-zA-Z0-9]{22}$", job_id):
        raise ValueError(
            "Deep research job_id must be a valid Modal sandbox name: "
            "64 characters or fewer, using only alphanumeric characters, dashes, periods, and underscores."
        )
    return job_id


def _create_sandbox_backend(config: SandboxConfig, job_id: str) -> Any:
    if config.provider == "modal":
        return _create_modal_backend(config, job_id)
    raise ValueError(f"Unsupported sandbox provider: {config.provider}. Supported providers: modal")


def _create_modal_backend(config: SandboxConfig, job_id: str) -> Any:
    return _LazyModalSandboxBackend(config, job_id)


class _LazyModalSandboxBackend(BaseSandbox):
    """Job-scoped Modal backend that creates and recreates the sandbox on demand."""

    def __init__(self, config: SandboxConfig, job_id: str) -> None:
        self.config = config
        self.sandbox_name = _validate_modal_sandbox_name(job_id)
        self._backend: Any | None = None
        self._lock = threading.Lock()

        try:
            import langchain_modal  # noqa: F401
            import modal  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "The Modal sandbox backend requires the `langchain-modal` and `modal` packages. "
                "Install the updated AIQ dependencies and run `modal setup` before enabling a Modal sandbox."
            ) from exc

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


def _create_modal_backend_now(config: SandboxConfig, sandbox_name: str, *, force_new: bool = False) -> Any:
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
    if config.python_packages:
        image = image.pip_install(*config.python_packages)
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
