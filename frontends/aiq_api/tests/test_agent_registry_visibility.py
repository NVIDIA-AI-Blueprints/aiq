# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_agent_config_defaults_to_public():
    from aiq_api.registry import AgentConfig

    config = AgentConfig(
        class_path="aiq_agent.agents.deep_researcher.agent.DeepResearcherAgent",
        config_name="deep_research_agent",
    )

    assert config.public is True


def test_register_agent_can_mark_internal(monkeypatch):
    from aiq_api import registry

    monkeypatch.setattr(registry, "AGENT_REGISTRY", {})

    registry.register_agent(
        agent_type="report_rewriter",
        class_path="aiq_agent.agents.report_rewriter.agent.ReportRewriterAgent",
        config_name="deep_research_agent",
        public=False,
    )

    assert registry.AGENT_REGISTRY["report_rewriter"].public is False


def test_default_registry_contains_internal_report_rewriter():
    from aiq_api.registry import AGENT_REGISTRY

    assert AGENT_REGISTRY["report_rewriter"].class_path == (
        "aiq_agent.agents.report_rewriter.agent.ReportRewriterAgent"
    )
    assert AGENT_REGISTRY["report_rewriter"].config_name == "deep_research_agent"
    assert AGENT_REGISTRY["report_rewriter"].public is False


@pytest.mark.asyncio
async def test_list_agents_excludes_internal_agents(monkeypatch):
    import aiq_api.routes.jobs as jobs_routes
    from aiq_api.registry import AgentConfig

    monkeypatch.setattr(
        jobs_routes,
        "AGENT_REGISTRY",
        {
            "deep_researcher": AgentConfig(
                class_path="aiq_agent.agents.deep_researcher.agent.DeepResearcherAgent",
                config_name="deep_research_agent",
                description="Deep",
            ),
            "report_rewriter": AgentConfig(
                class_path="aiq_agent.agents.report_rewriter.agent.ReportRewriterAgent",
                config_name="deep_research_agent",
                description="Internal",
                public=False,
            ),
        },
    )

    app = FastAPI()
    await jobs_routes.register_job_routes(
        app,
        builder=SimpleNamespace(),
        worker=SimpleNamespace(_dask_available=False, _job_store=None),
    )

    with TestClient(app) as client:
        response = client.get("/v1/jobs/async/agents")

    assert response.status_code == 200
    assert response.json() == {
        "agents": [
            {
                "agent_type": "deep_researcher",
                "description": "Deep",
            }
        ]
    }
