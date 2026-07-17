# Recorded Nimble response fixtures

Real `NimbleSearchRetriever.ainvoke()` responses, captured at the SDK boundary
(the exact seam the unit tests mock) and replayed by
`test_nimble_recorded_replay.py` to exercise the full provider pipeline with no
network and no credentials.

## Provenance

| File | Captured | Query | Config |
|---|---|---|---|
| `recorded_lite_response.json` | 2026-07-10 | `NVIDIA CUDA Toolkit documentation` | `search_depth=lite`, `max_results=5`, `focus=general`, `country=US`, `locale=en` |
| `recorded_deep_response.json` | 2026-07-10 | `NVIDIA CUDA Toolkit documentation` | `search_depth=deep`, `max_results=5`, `focus=general`, `country=US`, `locale=en` |

The query matches the live integration test's `CANNED_QUERY`, so the recorded
and live layers certify the same scenario.

## Redaction contract

Fixtures are redacted **by construction**: capture happens at the retriever's
return value (a list of documents), never at the HTTP layer, so request/response
headers and auth material are never present. Only the fields the provider
consumes are kept — `page_content` (truncated to 2000 chars) and the
`url` / `title` / `description` / `position` / `entity_type` metadata keys.

## Refreshing a fixture

```python
import asyncio, json
from langchain_nimble import NimbleSearchRetriever  # requires NIMBLE_API_KEY

KEPT = ("url", "title", "description", "position", "entity_type")
retriever = NimbleSearchRetriever(max_results=5, search_depth="lite", focus="general", country="US", locale="en")
docs = asyncio.run(retriever.ainvoke("NVIDIA CUDA Toolkit documentation"))
payload = {
    "_description": "Recorded NimbleSearchRetriever.ainvoke() response, search_depth=lite",
    "_captured": "YYYY-MM-DD",
    "_query": "NVIDIA CUDA Toolkit documentation",
    "_config": {"max_results": 5, "search_depth": "lite", "focus": "general", "country": "US", "locale": "en"},
    "_redaction": "only url/title/description/position/entity_type/page_content kept; page_content truncated to 2000 chars; no headers/auth",
    "documents": [
        {"page_content": (d.page_content or "")[:2000], "metadata": {k: (d.metadata or {}).get(k, "") for k in KEPT}}
        for d in docs
    ],
}
print(json.dumps(payload, indent=2, ensure_ascii=False))
```

Update the `_captured` date and re-run the replay tests after refreshing.

Licensed under the Apache License, Version 2.0 (SPDX-License-Identifier: Apache-2.0);
JSON cannot carry a license header, so this note covers the fixture files.
