<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Prompts

Each agent in the AI-Q blueprint uses [Jinja2](https://jinja.palletsprojects.com/) templates to define its system prompt. These templates control the agent's persona, instructions, output format, and behavior. By editing these templates you can customize how agents reason, what they prioritize, and how they format responses -- all without modifying Python code.

## Prompt Template Inventory

| Template | Agent | Purpose |
|----------|-------|---------|
| `src/aiq_agent/agents/chat_researcher/prompts/intent_classification.j2` | Intent Classifier | Classifies queries as meta or research, determines depth (shallow/deep), generates meta responses |
| `src/aiq_agent/agents/shallow_researcher/prompts/researcher.j2` | Shallow Researcher | Defines the research persona, tool usage strategy, source hierarchy, and citation rules |
| `src/aiq_agent/agents/deep_researcher/prompts/orchestrator.j2` | Deep Research Orchestrator | Coordinates the multi-phase research workflow, delegates to sub-agents, writes the final report |
| `src/aiq_agent/agents/deep_researcher/prompts/planner.j2` | Deep Research Planner | Generates evidence-grounded research plans with TOC structure and search queries |
| `src/aiq_agent/agents/deep_researcher/prompts/researcher.j2` | Deep Research Researcher | Gathers and synthesizes information from search tools with inline citations |
| `src/aiq_agent/agents/clarifier/prompts/research_clarification.j2` | Clarifier | Determines whether a research request needs clarification, asks focused follow-up questions |
| `src/aiq_agent/agents/clarifier/prompts/plan_generation.j2` | Clarifier (Plan) | Generates a lightweight research plan after clarification is complete |

## Template Directory Structure

Each agent stores its prompts in a `prompts/` subdirectory co-located with the agent code:

```
src/aiq_agent/agents/
    shallow_researcher/
        prompts/
            researcher.j2              # Single system prompt
    deep_researcher/
        prompts/
            orchestrator.j2            # Orchestrator prompt
            planner.j2                 # Research planner prompt
            researcher.j2              # Sub-researcher prompt
    clarifier/
        prompts/
            plan_generation.j2         # Research plan generation
            research_clarification.j2  # Clarification prompt
    chat_researcher/
        prompts/
            intent_classification.j2   # Routing prompt
```

The naming convention follows the template's role: `researcher.j2`, `orchestrator.j2`, `planner.j2`.

## How Templates Are Loaded

At runtime, templates flow through two utility functions in `src/aiq_agent/common/prompt_utils.py`:

```
prompts/researcher.j2  (Jinja2 source)
        │
        ▼
  load_prompt()         (reads file from disk)
        │
        ▼
  render_prompt_template()  (renders with variables)
        │
        ▼
  SystemMessage(content=...)  (sent to LLM)
```

### `load_prompt(path, name)`

Loads a raw template file from the agent's `prompts/` directory. Automatically appends `.j2` if the file is not found by exact name.

```python
from aiq_agent.common import load_prompt

# Load the template file as a string
template = load_prompt(Path(__file__).parent / "prompts", "researcher")
```

### `render_prompt_template(template, **kwargs)`

Renders a Jinja2 template string with the provided variables. Uses `jinja2.StrictUndefined` so that missing variables raise errors rather than producing silent empty strings.

```python
from aiq_agent.common import render_prompt_template

rendered = render_prompt_template(
    template,
    current_datetime="2026-02-16 10:30:00",
    tools=tools,
    user_info={"name": "Alice", "email": "alice@example.com"},
)
```

## Template Variables

Each template receives different variables depending on the agent context.

### Intent Classification

| Variable | Type | Description |
|----------|------|-------------|
| `current_datetime` | `str` | Current date and time string |
| `user_info` | `dict` or `None` | User context with `name` and `email` keys |
| `tools` | `list[dict]` | Available tools (each has `name` and `description` keys) |
| `query` | `str` | The user's query text |

### Shallow Researcher

| Variable | Type | Description |
|----------|------|-------------|
| `current_datetime` | `str` | Current date and time string |
| `user_info` | `dict` or `None` | User context with `name` and `email` keys |
| `tools` | `list[dict]` | Available tools (each has `name` and `description` keys) |
| `available_documents` | `list[dict]` or `None` | Uploaded documents with `file_name` and `summary` keys |

### Deep Research Orchestrator

| Variable | Type | Description |
|----------|------|-------------|
| `current_datetime` | `str` | Current date and time string |
| `clarifier_result` | `str` or `None` | Clarification context from the clarifier agent |
| `available_documents` | `list[dict]` or `None` | Uploaded documents with `file_name` and `summary` keys |
| `tools` | `list[dict]` | Available tools (each has `name` and `description` keys) |

### Deep Research Planner

| Variable | Type | Description |
|----------|------|-------------|
| `tools` | `list[dict]` | Available search tools (each has `name` and `description` keys) |
| `available_documents` | `list[dict]` or `None` | Uploaded documents with `file_name` and `summary` keys |

### Deep Research Researcher

| Variable | Type | Description |
|----------|------|-------------|
| `current_datetime` | `str` | Current date and time string |
| `tools` | `list[dict]` | Available search tools (each has `name` and `description` keys) |
| `available_documents` | `list[dict]` or `None` | Uploaded documents with `file_name` and `summary` keys |

### Research Clarification

| Variable | Type | Description |
|----------|------|-------------|
| `clarifier_result` | `str` or `None` | Previous clarification context (for multi-turn clarification) |
| `available_documents` | `list[dict]` or `None` | Uploaded documents with `file_name` and `summary` keys |
| `tools` | `list[dict]` | Available tools (each has `name` and `description` keys) |
| `tool_names` | `list[str]` | List of tool name strings extracted from `tools` |

### Plan Generation

| Variable | Type | Description |
|----------|------|-------------|
| `clarifier_context` | `str` or `None` | Context from the clarification dialog |
| `feedback_history` | `list[str]` or `None` | Previous plan feedback from the user (for iterative plan refinement) |

## Modifying Prompts

### Editing Existing Templates

The most common customization is editing the `.j2` files directly. Since templates are loaded from disk at startup, changes take effect on the next application restart.

**Example: Making the shallow researcher more concise**

Open `src/aiq_agent/agents/shallow_researcher/prompts/researcher.j2` and modify the citation rules section:

```jinja
{#- 5. CITATION & FORMATTING -#}
## Citation Rules (STRICT)
Every claim must end with [1]. You MUST include a `**References:**` section.
- **Format**: `- [N] Title/Filename - URL/Citation`
- **Brevity**: Keep answers under 500 words unless the query explicitly asks for detail.
```

### Key Sections to Customize

Each template has well-defined sections you can target:

- **Intent Classifier** (`intent_classification.j2`) — Classification rules, depth determination, meta response style, output JSON schema
- **Shallow Researcher** (`researcher.j2`) — Source hierarchy, research rules, citation format, response formatting
- **Deep Research Orchestrator** (`orchestrator.j2`) — Workflow steps, report length targets, citation guidelines, synthesis guidelines
- **Deep Research Planner** (`planner.j2`) — TOC structure, query generation guidelines, research cycle instructions, output JSON schema
- **Deep Research Researcher** (`researcher.j2`) — Research protocol, source prioritization, tool call budget, citation format
- **Clarifier** (`research_clarification.j2`) — What counts as "sufficiently specified", question style, multi-turn policy
- **Plan Generation** (`plan_generation.j2`) — Plan structure, section naming rules, output JSON format

### Creating a New Template

To create a new prompt template for a custom or modified agent:

**Step 1: Create the file**

```bash
touch src/aiq_agent/agents/my_agent/prompts/system.j2
```

**Step 2: Write the template**

A well-structured prompt template has clearly defined sections:

```jinja
{#- 1. CONTEXT -#}
Current date and time: {{ current_datetime }}

You are a specialized research agent.

{#- 2. TOOLS -#}
## Available Tools
{% if tools %}
{% for tool in tools %}- **{{ tool.name }}**: {{ tool.description }}
{% endfor %}
{% else %}
**No tools available.**
{% endif %}

{#- 3. INSTRUCTIONS -#}
## Instructions
- Research the user's question thoroughly using the available tools.
- Always cite your sources with numbered references.
- If no results are found, state this clearly.

{#- 4. OUTPUT FORMAT -#}
## Response Format
Provide your answer with inline citations [1], [2], etc.
End with a **References:** section listing all sources.
```

**Step 3: Load it in your agent**

```python
class MyAgent:
    def __init__(self, ...):
        self.system_prompt = load_prompt(AGENT_DIR / "prompts", "system")

    async def run(self, query: str) -> str:
        rendered = render_prompt_template(
            self.system_prompt,
            tools=self._build_tools_info(),
            current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        # Use rendered as SystemMessage content
```

### Multi-Prompt Agents

Some agents use multiple prompts for different roles. The deep researcher loads three separate templates:

```python
self.orchestrator_prompt = load_prompt(AGENT_DIR / "prompts", "orchestrator")
self.planner_prompt = load_prompt(AGENT_DIR / "prompts", "planner")
self.researcher_prompt = load_prompt(AGENT_DIR / "prompts", "researcher")
```

Each prompt is rendered with different context variables. This enables role specialization, independent tuning (through the GA optimizer), and token efficiency.

## Jinja2 Patterns

The templates use several Jinja2 patterns worth understanding before editing:

### Tool Detection

Templates detect available tool categories using namespace variables. The `namespace()` pattern is necessary because Jinja2's scoping rules prevent setting variables inside `for` loops that persist outside the loop.

```jinja
{% set ns = namespace(has_web=false, has_paper=false) %}
{% for tool in tools %}
  {% set t_name = tool.name.lower() %}
  {% if 'web' in t_name or 'tavily' in t_name %}
    {% set ns.has_web = true %}
  {% endif %}
{% endfor %}
```

### Conditional Rendering

Templates adapt based on which tools are available:

```jinja
{% if ns.has_web %}
4. **Web Search**: Use for general facts, news, or when other sources are unavailable.
{% endif %}
```

For advanced Jinja2 patterns (source hierarchy, default values, whitespace control), refer to the existing templates in `src/aiq_agent/agents/*/prompts/`.

## Testing Templates

Set the `DEBUG_PROMPTS` environment variable to log rendered prompts:

```bash
DEBUG_PROMPTS=1 .venv/bin/nat run --config_file configs/my_config.yml --input "test query"
```

This logs the fully rendered system prompt before each LLM call, letting you verify variable substitution and conditional rendering.

## Best Practices

1. **Test changes incrementally.** Modify one section at a time and verify the output before changing more. Run the application with `--input "your test query"` for quick iteration.

2. **Preserve the output format.** Many agents parse the LLM response as JSON (intent classifier, planner, clarifier). If you modify the output schema section, update the corresponding Python parser.

3. **Keep tool detection logic intact.** The `{% set ns = namespace(...) %}` blocks enable templates to adapt to different tool configurations. Removing them can cause incorrect instructions when tools are added or removed.

4. **Use Jinja2 comments for documentation.** Add `{#- ... -#}` comments to explain non-obvious prompt engineering decisions for future maintainers.

5. **Watch token budgets.** Longer system prompts consume tokens from the model's context window. This matters most for the deep research orchestrator, which needs context space for sub-agent reports.

6. **Match the existing style.** The templates use a consistent Markdown structure with headers, bold text, and numbered lists. Following this pattern helps the LLM parse instructions reliably.

7. **Test with multiple models.** Different LLMs interpret prompt instructions differently. If you switch models (refer to [Swapping Models](./swapping-models.md)), verify that the prompts still produce the expected behavior.

## Related

- [Configuration Reference](./configuration-reference.md) -- Full YAML config schema
- [Swapping Models](./swapping-models.md) -- Change which LLMs agents use
