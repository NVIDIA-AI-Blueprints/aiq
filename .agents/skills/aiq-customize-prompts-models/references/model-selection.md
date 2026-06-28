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
    _type: nim          # `openai` is also supported (also takes model_name)
    model_name: <a cheaper model>
```

## Assign a model to an agent role

Agents expose per-role LLM fields, but the two agents wire them differently — so
check the agent you are editing.

**Deep research agent** (`src/aiq_agent/agents/deep_researcher/register.py`)
defines `orchestrator_llm` (required) plus `source_router_llm`, `researcher_llm`,
`planner_llm`, and `writer_llm` (`LLMRef | None`). It seeds the provider default
from `orchestrator_llm` (`LLMProvider.set_default(...)`) and binds each set role
with `LLMProvider.configure(LLMRole.<ROLE>, llm)`
(`src/aiq_agent/common/llm_provider.py`). Field → role:

| Config field | `LLMRole` |
| :-- | :-- |
| `orchestrator_llm` (required) | `ORCHESTRATOR` — also the provider default |
| `source_router_llm` | `ROUTER` |
| `researcher_llm` | `RESEARCHER` |
| `planner_llm` | `PLANNER` |
| `writer_llm` | `REPORT_WRITER` |

An unset role falls back to the provider default (the `orchestrator_llm` model).
There is **no** generic `llm` field on the deep research agent.

**Clarifier** (`src/aiq_agent/agents/clarifier/register.py`) defines `llm` (its
default) and `planner_llm`. It does **not** use `LLMProvider.configure` for the
role — it passes `planner_llm` straight to the agent constructor, and `planner_llm`
falls back to `llm` when unset.

```yaml
functions:
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_super_llm   # required; also the default for unset roles
    source_router_llm: nemotron_super_llm
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
./scripts/start_cli.sh --config_file <the config where you set the role LLMs>   # agent starts with the assigned models
uv run pytest tests/aiq_agent/agents/deep_researcher
```

Expected: the agent starts with the configured models and its tests pass. A bare
`start_cli.sh` runs the fixed default config, so pass the config you edited. Every
role ref must resolve to an entry in `llms:`.
