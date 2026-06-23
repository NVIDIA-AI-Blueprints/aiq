<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Model selection

Authoritative sources: `docs/source/customization/swapping-models.md` and the
`llms` section of `docs/source/customization/configuration-reference.md`.

## Define models once, reference them by name

Declare each model in the config `llms:` section, then reference it by name from
an agent. Do not hard-code model names in Python.

```yaml
llms:
  nemotron_super_llm:
    _type: nim
    model_name: <a capable model>
  gpt_oss_llm:
    _type: nim          # `openai` is also supported
    model_name: <a cheaper model>
```

## Assign a model to an agent role

Agents expose per-role LLM fields so you can use different models for different
jobs. For example, `src/aiq_agent/agents/deep_researcher/register.py` defines
`orchestrator_llm` (required) plus `source_router_llm`, `researcher_llm`,
`planner_llm`, and `writer_llm` (`LLMRef | None`); the clarifier defines
`planner_llm`. When a role field is set, the agent resolves the ref via
`builder.get_llm(...)` and binds it to a role through
`LLMProvider.configure(LLMRole.<ROLE>, llm)` in
`src/aiq_agent/common/llm_provider.py`. When unset, the role falls back to the
agent's default `llm`.

```yaml
functions:
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_super_llm   # required
    researcher_llm: nemotron_super_llm
    planner_llm: gpt_oss_llm               # cheaper model for planning
    writer_llm: gpt_oss_llm
```

This mirrors the real configs (for example
`configs/config_domain_routing_and_skills.yml`); copy field names from there
rather than guessing.

## Swapping to a self-hosted NIM

Follow `swapping-models.md`: run the NIM locally, then point the `llms:` entry's
endpoint/model at it. Mind the hosted-API limitations and mitigations the doc
lists.

## Validation

```bash
./scripts/start_cli.sh           # confirm the agent starts with the assigned model
uv run pytest tests -k "<agent>"
```

Expected: the agent starts with the configured models and the affected tests
pass. Every role ref must resolve to an entry in `llms:`.
