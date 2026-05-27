# AIQ Research Skill

## Overview

`aiq-research` sends research-shaped user requests to a running NVIDIA AI-Q Blueprint backend. It checks backend health,
uses routed `/chat`, polls asynchronous deep research jobs, and returns final reports with citations intact.

## Prerequisites

This skill requires Python 3.11+, network access to a reachable local or self-hosted AI-Q backend, and `AIQ_SERVER_URL`
when the backend is not running at `http://localhost:8000`. The helper script uses only Python standard-library modules.
See `SKILL.md` for the canonical prerequisite checklist and authentication boundary.

## Canonical Location

This repository keeps the catalog-bound skill at:

```text
skills/aiq-research/
```

Install by copying or symlinking the full `aiq-research` directory into the skill location used by your coding harness.
The installed directory must contain `SKILL.md` at its root.

## Quick Start

Check the backend:

```bash
python3 scripts/aiq.py health
```

Send a routed research request:

```bash
python3 scripts/aiq.py chat "Compare local AIQ deep research with a standard web search workflow"
```

Resume polling when AI-Q returns a deep research job ID:

```bash
python3 scripts/aiq.py research_poll <JOB_ID>
```

Expected result: `health` returns JSON, `chat` returns either a direct JSON response or a job ID, and `research_poll`
returns the final report JSON when the job completes.

## Structure

```text
aiq-research/
|-- SKILL.md
|-- LICENSE
|-- README.md
|-- evals/
|   `-- evals.json
`-- scripts/
    `-- aiq.py
```

`SKILL.md` contains the agent-facing workflow. `scripts/aiq.py` is the standard-library Python client used by the skill.

## Quick Verification

From the installed skill directory, run:

```bash
python3 scripts/aiq.py
```

Expected output starts with:

```text
Usage: aiq.py <command> [args]
```

## Version Compatibility

This skill is designed for NVIDIA AI-Q Blueprint version 2.1.0. It follows semantic version compatibility:

- Major versions must match.
- Blueprint minor version must be equal to or newer than the skill minor version.
- Patch version differences do not affect compatibility.

## License

Copyright (c) 2026 NVIDIA Corporation. All rights reserved.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for full license text.

## Copyright

Copyright (c) 2026 NVIDIA Corporation. All rights reserved.
