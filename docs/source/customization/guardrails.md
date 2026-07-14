<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Guardrails

AI-Q can use NeMo Guardrails through NeMo Agent Toolkit middleware to evaluate selected workflow and agent-boundary inputs and outputs. Guardrails can pass content through unchanged, block content with a configured refusal, or modify selected fields before execution continues.

AI-Q provides middleware types for workflow, shallow-research, and deep-research boundaries. That capability does not
mean every boundary is active whenever its middleware is defined. In
`configs/config_web_default_guardrails.yml`, the workflow middleware is explicitly attached to the workflow. The async
deep-research runner selects `deep_agent_guardrails` because its `workflow_functions` targets `deep_research_agent`.
The checked-in profile does **not** attach `shallow_agent_guardrails` to `shallow_research_agent`, so shallow guardrails
are not active until that middleware reference is added to the function.

## Guarded Boundaries

| Boundary | Middleware | Applies To |
| --- | --- | --- |
| Workflow | `workflow_guardrails` | Workflow input and final assistant response; active when attached under `workflow.middleware`. |
| Shallow researcher | `shallow_agent_guardrails` | Shallow input or output message content; active when attached under `functions.shallow_research_agent.middleware`. |
| Deep researcher | `deep_agent_guardrails` | Deep input or output message content; the async runner selects it when `workflow_functions` targets `deep_research_agent`. |

These middleware types use NAT/NeMo Guardrails for policy evaluation at AI-Q workflow and agent boundaries.

## Guardrail Decisions

At each configured boundary, guardrails can make one of three decisions:

| Decision | Behavior |
| --- | --- |
| Pass | Continue with the original input or output. |
| Modify | Replace the selected input or output field with the modified content returned by the rail. |
| Block | Return the configured refusal response instead of continuing with the blocked content. |

Input-rail evaluation exceptions are caught, logged, and converted to the middleware refusal response. Output-rail
evaluation exceptions are not converted to a refusal; they propagate and fail the invocation.

## Configuration Shape

The guardrails configuration is placed in the top-level `middleware` section. Defining an entry makes that middleware
available; attach it to the workflow or function that should be guarded. The `guardrails` block uses NAT/NeMo
Guardrails configuration. Refer to `configs/config_web_default_guardrails.yml` for the full field-selection paths used by
each boundary.

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

Add the shallow attachment shown above to activate shallow enforcement in the reference profile. For async deep
research, the worker does not invoke the registered NAT function directly, so the AI-Q runner reconstructs the function
middleware chain and selects middleware whose `workflow_functions` includes `deep_research_agent`. You can also list
middleware directly on a function, but do not configure the same middleware through both mechanisms for the same async
worker function.

## Field Selection

The `workflow_functions` entry names the function schema used for field selection and defines which string fields
guardrails evaluate and can modify. The async deep-research runner also uses that target to select middleware around its
direct worker call. For the normal shallow function path, `workflow_functions` alone is not an attachment; add the
middleware name to `functions.shallow_research_agent.middleware`.

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

The shallow and deep researcher middleware types support this shape so input rails can evaluate user message content
and output rails can evaluate assistant message content. Only attached or runner-selected middleware is enforced.

## Supported Scope

Guardrails middleware is available at these AI-Q boundaries:

- Workflow input
- Workflow output
- Shallow researcher input and output messages
- Deep researcher input and output messages

The reference profile actively guards the workflow and async deep researcher as described above. It does not enforce all
three boundaries by default.

For the complete YAML schema and general configuration conventions, refer to [Configuration Reference](./configuration-reference.md).
