---
name: aiq-customize-prompts-models
description: Use when customizing AI-Q agent behavior through Jinja2 prompt templates or per-agent model selection — editing prompts under src/aiq_agent/agents/*/prompts/, adding template variables, or assigning/swapping LLMs per agent role via config (the llms section plus per-agent fields like orchestrator_llm, planner_llm, researcher_llm, writer_llm, source_router_llm).
license: Apache-2.0
compatibility: Claude Code, Codex, Cursor, OpenCode, and Agent Skills-compatible tools.
metadata:
  version: "0.1.0"
  source-repo: "NVIDIA-AI-Blueprints/aiq"
  tags: "aiq nemo-agent-toolkit prompts models jinja2 customization"
allowed-tools: Read Bash Edit
---

# Customize AI-Q Prompts and Models

Use this skill when a developer wants to change *how* an AI-Q agent reasons or
*which* model it uses — by editing a Jinja2 prompt template or by assigning a
different LLM to an agent role — without changing agent code. AI-Q agent behavior
is driven by prompts and config, so most tuning is a template or YAML change.

## Start Here

- Confirm the change is prompt or model customization, not new tool/agent logic.
  For a new retrieval source use `aiq-add-data-source`; for a new tool use
  `aiq-add-tool`.
- Read the authoritative docs and the existing templates/config below first.
- Prefer editing an existing template or config field over adding new machinery.
- Keep the prompt's STRICT citation rules intact, and never hard-code a model
  name where an `llms:` ref belongs.

## Authoritative References

- `docs/source/customization/prompts.md`: canonical prompt guide — template
  inventory, `load_prompt(path, name)`, `render_prompt_template(template, ...)`,
  template variables, the STRICT citation rules, and how to edit or add a template.
- `docs/source/customization/swapping-models.md`: choosing hosted vs. self-hosted
  NIMs and pointing config at them.
- `docs/source/customization/configuration-reference.md`: the `llms` section and
  each agent's config fields (`deep_research_agent`, `clarifier_agent`, …).
- `src/aiq_agent/common/prompt_utils.py`: `load_prompt` and
  `render_prompt_template`.
- `src/aiq_agent/common/llm_provider.py`: `LLMRole` and `LLMProvider.configure`,
  which bind a resolved LLM to an agent role.
- Templates to model on: `src/aiq_agent/agents/deep_researcher/prompts/*.j2`
  (orchestrator, planner, researcher, source_router, writer) and
  `src/aiq_agent/agents/clarifier/prompts/*.j2`.

Longer procedures live in this bundle:

- [references/prompt-templates.md](references/prompt-templates.md): where templates
  live, how they load and render, template variables, citation rules, and how to
  edit or add one safely.
- [references/model-selection.md](references/model-selection.md): the `llms`
  section, per-agent LLM fields, role binding via `LLMProvider`, and swapping models.

## Workflow

1. Identify the target agent and whether the change is a prompt or a model.
2. For a prompt: edit the relevant `src/aiq_agent/agents/<agent>/prompts/*.j2`
   template; keep its variables and citation rules intact (see the references).
3. For a model: add or point an `llms:` entry in the config and set the agent's
   role field (e.g. `orchestrator_llm`, `planner_llm`, `researcher_llm`,
   `writer_llm`, `source_router_llm`) to that ref — do not edit Python to swap a
   model.
4. Keep token cost in mind: prefer reordering static instructions before dynamic
   content (KV-cache reuse) and a cheaper model for low-stakes roles.
5. Validate (below): lint any changed Python, run the affected agent tests, and
   smoke-run the CLI to confirm templates load and the agent uses the new model.
6. Summarize changed files and paste the validation evidence.

## Validation

Run the narrowest checks first; broaden only if you touched shared code.

```bash
uv run ruff check src/aiq_agent             # only if you changed Python
uv run pytest tests -k "<agent or prompt>"  # affected agent/prompt tests
./scripts/start_cli.sh                       # smoke: templates load, agent runs
```

Expected: the agent loads its templates without a Jinja2 error, runs with the
configured model, and the affected tests pass. A prompt-only or config-only change
needs no Python lint.

## Common Mistakes

- Breaking a template variable or the STRICT citation rules in
  `docs/source/customization/prompts.md`, which degrades report grounding.
- Hard-coding a model name in Python instead of using an `llms:` ref and the
  agent's role field, so the model can no longer be swapped from config.
- Editing the default `llm` when you meant a single role (e.g. only the
  `planner_llm`), changing every unset role's model unintentionally.
- Introducing a large dynamic prefix that defeats KV-cache reuse and raises cost.
- Pointing an agent's role at a model whose entry is not defined in `llms:`.

## Related Skills

- `aiq-add-tool`
- `aiq-add-data-source`
- `aiq-release-qa`
- `aiq-prepare-pr`
