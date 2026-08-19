# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest

from aiq_agent.agents.chat_researcher.register import ChatDeepResearcherConfig
from aiq_agent.agents.chat_researcher.register import IntentClassifierConfig
from aiq_agent.agents.clarifier.register import ClarifierConfig
from aiq_agent.agents.deep_researcher.register import DeepResearchAgentConfig
from aiq_agent.agents.shallow_researcher.register import ShallowResearchAgentConfig


@pytest.mark.parametrize(
    "config_type",
    [
        IntentClassifierConfig,
        ChatDeepResearcherConfig,
        ClarifierConfig,
        ShallowResearchAgentConfig,
        DeepResearchAgentConfig,
    ],
)
def test_agent_configs_do_not_expose_legacy_verbose_switch(config_type: type) -> None:
    assert "verbose" not in config_type.model_fields
