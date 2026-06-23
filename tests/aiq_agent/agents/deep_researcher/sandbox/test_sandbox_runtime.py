# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the provider-neutral sandbox seam (registry, config, capabilities, base).

These run without a live Modal/OpenShell gateway: provider behavior is exercised
through small fakes, so only the framework logic (dispatch, fail-closed gate,
lazy creation, idempotency-gated retry, cleanup) is under test.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from aiq_agent.agents.deep_researcher.sandbox import CapabilityError
from aiq_agent.agents.deep_researcher.sandbox import SandboxCapabilities
from aiq_agent.agents.deep_researcher.sandbox import SandboxConfig
from aiq_agent.agents.deep_researcher.sandbox import SandboxProvider
from aiq_agent.agents.deep_researcher.sandbox import create_sandbox_backend
from aiq_agent.agents.deep_researcher.sandbox import register_sandbox_provider
from aiq_agent.agents.deep_researcher.sandbox import registered_providers
from aiq_agent.agents.deep_researcher.sandbox import verify_capabilities


class _RecoverableError(Exception):
    """Stand-in for a provider's transient/stale-sandbox error."""


class _RegisteredFake(SandboxProvider):
    """Minimal registered provider with conservative (default) capabilities."""

    provider_name = "registered-fake"

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities()

    def _create_session(self) -> Any:
        return MagicMock()


class _ScriptedProvider(SandboxProvider):
    """Provider that hands out caller-supplied sessions, for retry/lazy tests."""

    provider_name = "scripted"

    def __init__(self, config: SandboxConfig, job_id: str, sessions: list[Any]) -> None:
        super().__init__(config, job_id)
        self._sessions = sessions
        self.sessions_created = 0

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(supports_network_policy=True)

    def is_recoverable_error(self, exc: Exception) -> bool:
        return isinstance(exc, _RecoverableError)

    def _create_session(self) -> Any:
        session = self._sessions[self.sessions_created]
        self.sessions_created += 1
        return session


register_sandbox_provider("registered-fake", _RegisteredFake)


def _fake_config(**overrides: Any) -> SandboxConfig:
    base: dict[str, Any] = {"provider": "registered-fake", "block_network": False}
    base.update(overrides)
    return SandboxConfig(**base)


class TestRegistry:
    def test_builtin_providers_registered(self) -> None:
        assert "modal" in registered_providers()
        assert "openshell" in registered_providers()

    def test_create_unknown_provider_raises(self) -> None:
        config = _fake_config()
        object.__setattr__(config, "provider", "ghost")  # bypass field validation
        with pytest.raises(ValueError, match="Registered providers"):
            create_sandbox_backend(config, "job-1")

    def test_create_returns_provider_instance(self) -> None:
        backend = create_sandbox_backend(_fake_config(), "job-1")
        assert isinstance(backend, _RegisteredFake)


class TestSandboxConfig:
    def test_legacy_flat_modal_fields_lift_into_providers(self) -> None:
        config = SandboxConfig(
            provider="modal",
            app_name="aiq-deep-research",
            image="python:3.13-slim",
            python_packages=["pandas", "tabulate"],
        )
        assert config.providers.modal.app_name == "aiq-deep-research"
        assert config.providers.modal.image == "python:3.13-slim"
        assert config.providers.modal.python_packages == ("pandas", "tabulate")
        assert config.python_packages == ("pandas", "tabulate")

    def test_explicit_nested_takes_precedence_over_legacy(self) -> None:
        config = SandboxConfig(image="legacy:tag", providers={"modal": {"image": "nested:tag"}})
        assert config.providers.modal.image == "nested:tag"

    def test_provider_normalized_lowercase(self) -> None:
        assert SandboxConfig(provider="MODAL").provider == "modal"

    def test_default_workdir_and_artifact_dir(self) -> None:
        config = SandboxConfig()
        assert config.workdir == "/workspace"
        assert config.artifact_dir == "/workspace/aiq-artifacts"

    def test_unknown_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="Registered providers"):
            SandboxConfig(provider="does-not-exist")


class TestCapabilityGate:
    def test_block_network_requires_capability(self) -> None:
        config = _fake_config(block_network=True)  # _RegisteredFake declares no network policy
        with pytest.raises(CapabilityError, match="block_network"):
            create_sandbox_backend(config, "job-1")

    def test_passes_when_network_unblocked(self) -> None:
        backend = create_sandbox_backend(_fake_config(block_network=False), "job-1")
        assert isinstance(backend, _RegisteredFake)

    def test_artifact_capture_requires_download(self) -> None:
        caps = SandboxCapabilities(supports_network_policy=True, supports_artifact_download=False)
        config = SandboxConfig(provider="registered-fake", artifact_capture={"enabled": True})
        with pytest.raises(CapabilityError, match="download"):
            verify_capabilities(config, caps)


class TestNetworkPolicy:
    def test_legacy_block_network_true_maps_to_blocked(self) -> None:
        config = SandboxConfig(provider="registered-fake", block_network=True)
        assert config.network.mode == "blocked"
        assert config.block_network is True

    def test_legacy_block_network_false_maps_to_open(self) -> None:
        config = SandboxConfig(provider="registered-fake", block_network=False)
        assert config.network.mode == "open"
        assert config.block_network is False

    def test_explicit_network_wins_over_legacy_block_network(self) -> None:
        config = SandboxConfig(provider="registered-fake", block_network=True, network={"mode": "open"})
        assert config.network.mode == "open"
        assert config.block_network is False

    def test_allowlist_requires_hosts(self) -> None:
        with pytest.raises(ValueError, match="allowlist"):
            SandboxConfig(provider="registered-fake", network={"mode": "allowlist"})

    def test_allowlist_requires_capability(self) -> None:
        # _RegisteredFake declares neither network policy nor allowlist support.
        config = SandboxConfig(provider="registered-fake", network={"mode": "allowlist", "allow": ["pypi.org"]})
        with pytest.raises(CapabilityError, match="allowlist"):
            create_sandbox_backend(config, "job-1")

    def test_allowlist_passes_when_capability_declared(self) -> None:
        config = SandboxConfig(provider="registered-fake", network={"mode": "allowlist", "allow": ["pypi.org"]})
        verify_capabilities(config, SandboxCapabilities(supports_network_allowlist=True))


class TestEntryPointDiscovery:
    def test_entry_point_provider_is_discovered(self, monkeypatch: Any) -> None:
        from aiq_agent.agents.deep_researcher.sandbox import registry

        class _EntryPointProvider(_RegisteredFake):
            provider_name = "ep-fake"

        class _FakeEntryPoint:
            name = "ep-fake"

            def load(self) -> type[SandboxProvider]:
                return _EntryPointProvider

        def _fake_entry_points(*, group: str) -> list[Any]:
            assert group == registry.SANDBOX_PROVIDER_ENTRY_POINT_GROUP
            return [_FakeEntryPoint()]

        monkeypatch.setattr(registry, "_entry_points_loaded", False)
        monkeypatch.setattr("importlib.metadata.entry_points", _fake_entry_points)
        registry._SANDBOX_PROVIDERS.pop("ep-fake", None)
        try:
            assert registry.is_registered("ep-fake")
            assert "ep-fake" in registered_providers()
        finally:
            registry._SANDBOX_PROVIDERS.pop("ep-fake", None)

    def test_broken_entry_point_is_skipped(self, monkeypatch: Any) -> None:
        from aiq_agent.agents.deep_researcher.sandbox import registry

        class _BrokenEntryPoint:
            name = "broken"

            def load(self) -> type[SandboxProvider]:
                raise RuntimeError("boom")

        monkeypatch.setattr(registry, "_entry_points_loaded", False)
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [_BrokenEntryPoint()])
        # Must not raise; built-in resolution stays intact.
        registry._load_entry_point_providers()
        assert "broken" not in registry._SANDBOX_PROVIDERS
        assert "modal" in registered_providers()


class TestProviderLifecycle:
    def test_session_created_lazily(self) -> None:
        session = MagicMock()
        provider = _ScriptedProvider(_fake_config(), "job-1", sessions=[session])
        assert provider.sessions_created == 0
        provider.execute("echo ok", timeout=5)
        assert provider.sessions_created == 1
        session.execute.assert_called_once_with("echo ok", timeout=5)

    def test_idempotent_download_retries_on_recoverable_error(self) -> None:
        first = MagicMock()
        first.download_files.side_effect = _RecoverableError("gone")
        second = MagicMock()
        second.download_files.return_value = ["ok"]
        provider = _ScriptedProvider(_fake_config(), "job-1", sessions=[first, second])

        result = provider.download_files(["/workspace/a.png"])

        assert result == ["ok"]
        assert provider.sessions_created == 2  # recreated once

    def test_execute_does_not_retry_on_recoverable_error(self) -> None:
        first = MagicMock()
        first.execute.side_effect = _RecoverableError("gone")
        second = MagicMock()
        provider = _ScriptedProvider(_fake_config(), "job-1", sessions=[first, second])

        with pytest.raises(_RecoverableError):
            provider.execute("echo ok")

        # Non-idempotent op must NOT silently recreate + re-run on a fresh empty sandbox.
        assert provider.sessions_created == 1

    def test_execute_timeout_clamped_to_config_limit(self) -> None:
        session = MagicMock()
        session.execute.return_value = "ok"
        provider = _ScriptedProvider(_fake_config(timeout=1200), "job-1", sessions=[session])

        provider.execute("echo ok", timeout=120000)  # e.g. a tool passing milliseconds

        session.execute.assert_called_once_with("echo ok", timeout=1200)

    def test_execute_timeout_passthrough_when_within_limit(self) -> None:
        session = MagicMock()
        session.execute.return_value = "ok"
        provider = _ScriptedProvider(_fake_config(timeout=1200), "job-1", sessions=[session])

        provider.execute("echo ok", timeout=30)

        session.execute.assert_called_once_with("echo ok", timeout=30)

    def test_close_releases_session(self) -> None:
        session = MagicMock()
        provider = _ScriptedProvider(_fake_config(), "job-1", sessions=[session])
        provider.execute("echo ok")
        provider.close()
        session.close.assert_called_once()
        assert provider._session is None
