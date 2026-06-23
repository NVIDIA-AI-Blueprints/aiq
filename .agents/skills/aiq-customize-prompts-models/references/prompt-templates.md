<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Prompt templates

Authoritative source: `docs/source/customization/prompts.md`. This is a quick
operational summary; defer to that doc for the full template inventory and the
exact variables each agent expects.

## Where templates live

Each agent owns its Jinja2 templates under
`src/aiq_agent/agents/<agent>/prompts/*.j2`. For example, the deep researcher has
`orchestrator.j2`, `planner.j2`, `researcher.j2`, `source_router.j2`, `writer.j2`,
and `source_registry.j2`; the clarifier has `plan_generation.j2` and
`research_clarification.j2`.

## How templates load and render

- `load_prompt(path, name)` in `src/aiq_agent/common/prompt_utils.py` reads a
  template file as a string.
- `render_prompt_template(template, **kwargs)` (same module) renders it with
  Jinja2, injecting the documented template variables. See the "Template
  Variables" section of `prompts.md` for the exact variables per agent.

## Editing a template safely

1. Keep every `{{ variable }}` the agent passes in; removing one breaks rendering
   or silently drops context.
2. Preserve the **Citation Rules (STRICT)** section in `prompts.md` — report
   grounding depends on the model emitting citations exactly as instructed.
3. Prefer putting static instructions before dynamic content so the KV cache is
   reused across calls (lower latency and token cost).
4. Edit the `.j2` template, not the Python, for wording or structure changes.

## Adding a new template

Follow "Creating a New Template" in `prompts.md`: add the `.j2` file under the
agent's `prompts/` directory and load it with `load_prompt`. Keep variable names
consistent with what the agent renders.

## Validation

```bash
./scripts/start_cli.sh           # confirm the template loads (no Jinja2 error)
uv run pytest tests -k "<agent>"
```

Expected: the agent starts and renders the template without error, and the
affected tests pass.
