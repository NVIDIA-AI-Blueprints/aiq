<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Guardrails

AI-Q can use NeMo Guardrails through NeMo Agent Toolkit middleware to evaluate selected workflow and agent-boundary inputs and outputs. Guardrails can pass content through unchanged, block content with a configured refusal, or modify selected fields before execution continues.

The reference configuration is `configs/config_web_default_guardrails.yml`, which keeps the default web workflow and applies guardrails at the workflow, shallow researcher, and deep researcher boundaries.

## Guarded Boundaries

| Boundary | Middleware | Applies To |
| --- | --- | --- |
| Workflow | `workflow_guardrails` | Workflow input and final assistant response. |
| Shallow researcher | `shallow_agent_guardrails` | Shallow researcher input and output message content. |
| Deep researcher | `deep_agent_guardrails` | Deep researcher input and output message content. |

These middleware types use NAT/NeMo Guardrails for policy evaluation at AI-Q workflow and agent boundaries.

## Guardrail Decisions

At each configured boundary, guardrails can make one of three decisions:

| Decision | Behavior |
| --- | --- |
| Pass | Continue with the original input or output. |
| Modify | Replace the selected input or output field with the modified content returned by the rail. |
| Block | Return the configured refusal response instead of continuing with the blocked content. |

## Configuration Shape

The guardrails configuration is placed in the top-level `middleware` section, then attached to the workflow or function that should be guarded. The `guardrails` block uses NAT/NeMo Guardrails configuration. See `configs/config_web_default_guardrails.yml` for the full field-selection paths used by each boundary.

```yaml
middleware:
  workflow_guardrails:
    _type: workflow_guardrails
    guardrails:
      # NeMo Guardrails configuration.

  shallow_agent_guardrails:
    _type: shallow_agent_guardrails
    guardrails:
      # NeMo Guardrails configuration.

functions:
  shallow_research_agent:
    _type: shallow_research_agent
    middleware:
      - shallow_agent_guardrails

workflow:
  _type: chat_deepresearcher_agent
  middleware:
    - workflow_guardrails
```

The deep researcher uses the same attachment pattern with `_type: deep_agent_guardrails`.

## Field Selection

The `workflow_functions` entry does two things: it identifies the function that receives middleware, and it defines which string fields guardrails evaluate and can modify.

For nested response objects, selected fields can be dotted paths:

```yaml
workflow_functions:
  "<workflow>":
    choices:
      - message.content
```

For workflow-level guardrails, this selects `message.content` from each item in the final response `choices`.

Agent-boundary guardrails can also select message fields by message type. This lets the same agent state carry multiple message types while guardrails evaluate only the configured string fields.

```yaml
workflow_functions:
  shallow_research_agent:
    pre_invoke:
      messages:
        HumanMessage:
          - content
    post_invoke:
      messages:
        AIMessage:
          - content
```

In this example:

| Entry | Meaning |
| --- | --- |
| `pre_invoke` | Selects fields evaluated by input rails before the agent runs. |
| `post_invoke` | Selects fields evaluated by output rails after the agent returns. |
| `messages` | Selects the agent state's message list. |
| `HumanMessage` | Applies the listed field paths to user messages in that list. |
| `AIMessage` | Applies the listed field paths to assistant messages in that list. |
| `content` | Evaluates the message text. |

The shallow and deep researcher guardrails use this shape so input rails can evaluate user message content and output rails can evaluate assistant message content.

## Supported Scope

Guardrails are supported at these AI-Q boundaries:

- Workflow input
- Workflow output
- Shallow researcher input and output messages
- Deep researcher input and output messages

For the complete YAML schema and general configuration conventions, see [Configuration Reference](./configuration-reference.md).
