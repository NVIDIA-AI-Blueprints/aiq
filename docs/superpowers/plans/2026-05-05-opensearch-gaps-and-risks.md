# OpenSearch Gaps & Risks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps and risks surfaced by (a) the original PR evaluation and (b) the live-AOSS validation testing, so the `feat/opensearch-aoss` branch is mergeable as a complete v2.0 OpenSearch story.

**Architecture:** Eight focused tasks. Five are small code or doc fixes for surface-level bugs. One is a research-first task (the `/v1/chat/completions` `conversation_id` silent-drop). Two are PR-readiness tasks (DCO sign-off + final docs build). No new modules; every change lands in files already on the branch.

**Tech Stack:** Python (adapter + register), Markdown (Sphinx + MyST), bash (verification commands), `git` (rebase --signoff for DCO compliance).

**Pre-flight context the executing engineer needs:**
- The branch already has 19 commits ahead of `develop`: 6 foundation + 12 from the EKS reference deployment plan + 1 fix for asymmetric NIM embedding models (commit `619228a`).
- Live testing today proved the full stack works against AOSS: local ingest, Dask ingest, file deletion (AOSS-aware bulk-delete), 30-page PDF, retrieval with page citations.
- Three gotchas were observed during testing and are folded into this plan.

**Items deferred to a future plan:** TTL cleanup live test (needs `AIQ_TTL_CLEANUP_INTERVAL_SECONDS` override and patience), full EKS deploy walkthrough, multi-session concurrency load test.

**File inventory:**
- `sources/knowledge_layer/src/opensearch/adapter.py` — Tasks 1, 6.
- `sources/knowledge_layer/src/register.py` — Task 5 (potentially).
- `sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md` — Task 2.
- `docs/source/deployment/aws-opensearch-serverless.md` — Tasks 2, 3, 4, 6.
- `tests/knowledge_layer_tests/test_opensearch_adapter.py` — Task 1.
- Branch-wide commit history — Task 7.
- All docs source — Task 8.

---

### Task 1: Fail fast on missing `NVIDIA_API_KEY` for hosted-API ingestion

**Files:**
- Modify: `sources/knowledge_layer/src/opensearch/adapter.py:508` (ingestor `_embed_texts`)
- Modify: `sources/knowledge_layer/src/opensearch/adapter.py` retriever `_embed_texts` (line ~1342, may have shifted by ~6 lines after the input_type fix)
- Modify: `tests/knowledge_layer_tests/test_opensearch_adapter.py` (add unit test)

**Why:** Today the adapter calls `OpenAI(api_key=os.environ.get("NVIDIA_API_KEY", ""))` — empty-string fallback. If the env var is unset and the embedding endpoint is the hosted NVIDIA API, the call surfaces as a confusing 401 from `integrate.api.nvidia.com` instead of a clear "missing key" error. Surfaced in the original PR evaluation. NIM-on-EKS users (no key needed) should still work; only the *default* hosted-API path with a missing key should fail loudly.

- [ ] **Step 1: Write the failing test**

In `tests/knowledge_layer_tests/test_opensearch_adapter.py`, add:

```python
def test_ingestor_embed_raises_when_hosted_api_and_missing_key(monkeypatch):
    """Hosted NVIDIA API with no key should raise a clear error before HTTP."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "embed_base_url": "https://integrate.api.nvidia.com/v1",
        "start_ttl_cleanup": False,
    })
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        ingestor._embed_texts(["hello world"])


def test_ingestor_embed_allows_local_nim_without_key(monkeypatch):
    """Self-hosted NIM with no key should pass through without complaint."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "embed_base_url": "http://nim-embed.ns-nim.svc.cluster.local:8000/v1",
        "start_ttl_cleanup": False,
    })
    # Patch the OpenAI client so we don't hit the network; the test just
    # asserts no early-exit RuntimeError fired.
    class _FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.embeddings = type("E", (), {"create": staticmethod(lambda **kw: type("R", (), {"data": [type("D", (), {"embedding": [0.0] * 4})()]})())})()
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    result = ingestor._embed_texts(["hello"])
    assert result == [[0.0, 0.0, 0.0, 0.0]]
```

- [ ] **Step 2: Run tests, verify both fail**

```bash
uv run python -m pytest tests/knowledge_layer_tests/test_opensearch_adapter.py::test_ingestor_embed_raises_when_hosted_api_and_missing_key tests/knowledge_layer_tests/test_opensearch_adapter.py::test_ingestor_embed_allows_local_nim_without_key -v
```

Expected: both FAIL — the first because no error is raised, the second because the un-patched OpenAI client tries to make a real HTTP call.

- [ ] **Step 3: Implement the fix in both `_embed_texts` methods**

Replace the unguarded `os.environ.get("NVIDIA_API_KEY", "")` with a helper that fails on the hosted-API URL pattern only:

```python
# At module level, near other helpers:
def _resolve_embedding_api_key(embed_base_url: str) -> str:
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    is_hosted_nvidia = "integrate.api.nvidia.com" in (embed_base_url or "")
    if is_hosted_nvidia and not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is required for the hosted NVIDIA embeddings API "
            "(embed_base_url contains integrate.api.nvidia.com). Either set "
            "NVIDIA_API_KEY or override AIQ_EMBED_BASE_URL to a self-hosted NIM endpoint."
        )
    return api_key
```

Then in both `_embed_texts` methods:

```python
client = OpenAI(base_url=self.embed_base_url, api_key=_resolve_embedding_api_key(self.embed_base_url))
```

- [ ] **Step 4: Run tests, verify both pass**

```bash
uv run python -m pytest tests/knowledge_layer_tests/test_opensearch_adapter.py::test_ingestor_embed_raises_when_hosted_api_and_missing_key tests/knowledge_layer_tests/test_opensearch_adapter.py::test_ingestor_embed_allows_local_nim_without_key -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full adapter test suite to confirm no regressions**

```bash
uv run python -m pytest tests/knowledge_layer_tests/test_opensearch_adapter.py -q
```

Expected: all green.

- [ ] **Step 6: Commit with sign-off**

```bash
git add sources/knowledge_layer/src/opensearch/adapter.py \
        tests/knowledge_layer_tests/test_opensearch_adapter.py
git commit -s -m "fix(opensearch): fail fast when NVIDIA_API_KEY is missing for hosted API"
```

---

### Task 2: Document the OpenSearch backend as text-only

**Files:**
- Modify: `sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md` (in the OpenSearch section)
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (one-line callout near the workflow config section)

**Why:** The LlamaIndex backend supports table/image/chart extraction via `AIQ_EXTRACT_TABLES/IMAGES/CHARTS`. The OpenSearch ingestor currently only does text chunking — `_read_pdf_file` extracts page text, no VLM, no pdfplumber tables. AWS customers reading the doc may assume parity with v1.0 multimodal behavior. Either build it or explicitly call out the gap. This task does the explicit-callout option.

- [ ] **Step 1: Add a callout note in `KNOWLEDGE-LAYER-SETUP.md`**

Find the OpenSearch backend section (the one that begins "**OpenSearch (Self-hosted)**" and contains the example YAML). Immediately before the AOSS YAML block (the one with `opensearch_aws_service: aoss`), insert:

```markdown
> **Note: text-only ingestion.** The OpenSearch backend extracts plain text from PDFs, DOCX, and PPTX
> via `pypdf`/`docx2txt`/`python-pptx`. It does **not** currently honor `AIQ_EXTRACT_TABLES`,
> `AIQ_EXTRACT_IMAGES`, or `AIQ_EXTRACT_CHARTS` (those flags are LlamaIndex-only). For multimodal
> ingestion against OpenSearch, run the LlamaIndex backend instead, or use Foundational RAG which
> handles multimodal extraction server-side.
```

- [ ] **Step 2: Add the same note in the AOSS deployment doc**

In `docs/source/deployment/aws-opensearch-serverless.md`, find the `## Workflow Config` section. Immediately after the `Use \`configs/config_web_opensearch.yml\`:` line and before the YAML excerpt, insert:

```markdown
```{note}
**Text-only ingestion.** The OpenSearch backend extracts plain text from PDFs, DOCX, and PPTX. It does
not currently support table/image/chart extraction (those flags are LlamaIndex-only). For multimodal,
use the LlamaIndex backend or Foundational RAG.
```
```

- [ ] **Step 3: Render docs and verify**

```bash
uv run --extra docs sphinx-build -b html docs/source docs/_build/html
```

Expected: build succeeds with zero warnings.

- [ ] **Step 4: Commit with sign-off**

```bash
git add sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md \
        docs/source/deployment/aws-opensearch-serverless.md
git commit -s -m "docs(opensearch): explicit text-only callout for ingestion path"
```

---

### Task 3: Fix health-endpoint expected response in the deployment doc

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (the `## Verify the deployment` → `### 2. Backend health check` block)

**Why:** Live testing showed `/health` returns `{"status":"healthy"}`. Our deployment doc says `Expected: {"status":"ok"}`. Trivial doc inaccuracy, easy fix while we're here.

- [ ] **Step 1: Edit the expected-response line**

Find this block in `docs/source/deployment/aws-opensearch-serverless.md`:

```markdown
Expected: `{"status":"ok"}` (or equivalent — match the health route exposed by the deployed
`aiq_api` front end).
```

Replace with:

```markdown
Expected: `{"status":"healthy"}` (the `aiq_api` front end exposes a JSON health route at `/health`).
```

- [ ] **Step 2: Render docs**

```bash
uv run --extra docs sphinx-build -b html docs/source docs/_build/html
```

- [ ] **Step 3: Commit with sign-off**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -s -m "docs(opensearch): correct health endpoint expected response shape"
```

---

### Task 4: Add an AOSS visibility-delay note in the Verify section

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (the `## Verify the deployment` section)

**Why:** During PDF testing, the `_count` against AOSS returned 0 immediately after a successful bulk write — even though the AIQ status said `completed: true, chunks_created: 30`. After ~10 seconds the count caught up. This is documented AOSS eventual-consistency behavior, but customers running the verification script will hit it the first time and assume something is broken. A short callout in the verify section preempts the support ticket.

- [ ] **Step 1: Add the visibility note in step 4**

Find `### 4. Confirm the index appears in AOSS` in `docs/source/deployment/aws-opensearch-serverless.md`. Immediately after the existing prose ending "and the `smoke` collection listed by the AIQ API.", insert:

```markdown
```{note}
**AOSS visibility delay.** AOSS is eventually consistent for search after writes. A `_count` immediately
after a successful upload may report `0` for ~5–30 seconds before catching up. If the AIQ status says
`completed` but the AOSS console index browser shows zero docs, wait 30s and refresh — the index will
populate. This is also why the live-test suite includes a polling visibility wait.
```
```

- [ ] **Step 2: Render docs**

```bash
uv run --extra docs sphinx-build -b html docs/source docs/_build/html
```

- [ ] **Step 3: Commit with sign-off**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -s -m "docs(opensearch): note AOSS visibility delay in verification steps"
```

---

### Task 5: Triage the `conversation_id` silent-drop on `/v1/chat/completions`

**Files:** Triage-first; possibly modify `aiq_api` chat-completions route or the workflow config docs depending on findings.

**Why:** During the PDF retrieval test, sending `{"conversation_id": "papers", ...}` in the chat-completions request body had no effect — the agent always used the YAML default (`COLLECTION_NAME=smoke`). Customers reading the OpenAPI schema will assume `conversation_id` controls collection routing; today it doesn't. Either (a) honor it in the route handler or (b) remove it from the request schema. This task starts with research because the fix path depends on what the field was originally intended for.

- [ ] **Step 1: Locate the chat-completions request handler**

```bash
grep -rn 'chat/completions\|conversation_id' src/aiq_api 2>/dev/null || \
grep -rn 'chat/completions\|conversation_id' /Users/fdecarvalhop/Documents/projects/aiq/.venv/lib/python3.13/site-packages/aiq_api 2>/dev/null
```

Find the route registering `POST /v1/chat/completions`. Read it, identify whether `conversation_id` is present in the Pydantic request model and where (or if) it is ever read.

- [ ] **Step 2: Locate where `Context.conversation_id` is set**

```bash
grep -rn 'Context.*conversation_id\|set.*conversation_id\|context.*conversation' src/ /Users/fdecarvalhop/Documents/projects/aiq/.venv/lib/python3.13/site-packages/nat 2>/dev/null | head -20
```

Determine the actual mechanism the UI uses (likely a header, cookie, or different route).

- [ ] **Step 3: Decide and document the fix**

Two acceptable outcomes — pick based on what Step 1–2 reveal:

**Outcome A — honor the field.** If `conversation_id` is meant to flow to `Context.conversation_id`, add the wiring in the route handler:

```python
# Pseudocode — actual path TBD by Step 1
async def chat_completions(req: ChatCompletionsRequest, ...):
    if req.conversation_id:
        context.conversation_id = req.conversation_id
    # ... existing handler
```

Add a unit test if the route has a test harness.

**Outcome B — remove it from the schema.** If `conversation_id` is vestigial in this route (UI uses a header/cookie/different route), remove the field from the request model so the OpenAPI no longer advertises it:

```python
class ChatCompletionsRequest(BaseModel):
    messages: list[Message]
    stream: bool = False
    # conversation_id removed — see <route> for session control via <header/cookie>
```

Document the actual session-control mechanism in `KNOWLEDGE-LAYER-SETUP.md` so customers know where to set it.

- [ ] **Step 4: Run any affected tests**

```bash
uv run python -m pytest tests/ -q -k chat_completions 2>&1 | tail -20
```

Expected: green.

- [ ] **Step 5: Commit with sign-off**

```bash
git add <files-touched>
git commit -s -m "fix(api): honor conversation_id on /v1/chat/completions"
# OR
git commit -s -m "fix(api): drop unused conversation_id from /v1/chat/completions schema"
```

If Step 1 reveals this is outside the OpenSearch story (e.g., a long-standing `aiq_api` issue unrelated to v2.0 OpenSearch), STOP and report — it may belong in a separate PR rather than `feat/opensearch-aoss`.

---

### Task 6: Document the Dask-worker logging gotcha

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (the `## Architecture` or `## Troubleshooting` section)

**Why:** During Dask-mode testing, the dask-worker subprocess produced an empty stdout file even though it successfully wrote 3 docs to AOSS — the `DASK_DISTRIBUTED__LOGGING__DISTRIBUTED=warning` setting in `deploy/.env` cascaded into the worker's Python logging config. In EKS this is invisible because pod stdout is separately captured; locally during testing, it makes "did the worker actually do anything?" hard to confirm. A doc note saves the next person 30 minutes.

- [ ] **Step 1: Add a troubleshooting row**

Find the `## Troubleshooting` table in `docs/source/deployment/aws-opensearch-serverless.md`. Add a new row before the table closes:

```markdown
| Dask worker stdout is empty during local testing | `DASK_DISTRIBUTED__LOGGING__DISTRIBUTED=warning` (default in `deploy/.env`) silences worker logs. Ingestion still succeeds — verify by counting docs in AOSS, not by tailing the worker. | Override locally with `DASK_DISTRIBUTED__LOGGING__DISTRIBUTED=info` if you need worker logs during development. |
```

- [ ] **Step 2: Render docs**

```bash
uv run --extra docs sphinx-build -b html docs/source docs/_build/html
```

- [ ] **Step 3: Commit with sign-off**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -s -m "docs(opensearch): note Dask worker logging is silenced by default env"
```

---

### Task 7: DCO sign-off rebase across the branch

**Files:** All commits on `feat/opensearch-aoss` not yet signed (everything except commits made *during* this plan, which use `git commit -s` from Task 1 onward).

**Why:** CONTRIBUTING.md requires a `Signed-off-by:` trailer on every commit. The 19 commits before this plan's first sign-off don't have it. `git rebase --signoff` adds the trailer to every commit between develop and HEAD; commits already signed are left alone (idempotent).

- [ ] **Step 1: Verify which commits lack the trailer**

```bash
git log develop..HEAD --format='%h %s' | while read sha _; do
  if [ -z "$(git show -s --format='%(trailers:key=Signed-off-by,valueonly)' "$sha")" ]; then
    echo "MISSING: $sha"
  fi
done
```

Note the count and SHAs.

- [ ] **Step 2: Rebase with sign-off**

```bash
git rebase --signoff develop
```

This rewrites every commit's SHA but adds `Signed-off-by:` to those missing it.

- [ ] **Step 3: Verify all commits are signed**

Re-run Step 1's verification loop. Expected: no `MISSING:` lines.

- [ ] **Step 4: Spot-check a representative commit**

```bash
git log -1 --format='%B' HEAD~5
```

Expected: trailer block ends with both `Co-Authored-By: ...` and `Signed-off-by: Felipe Garcia <fdecarvalhop@nvidia.com>`.

No commit needed — the rebase already wrote the changes.

---

### Task 8: Final docs build + adapter test suite as a quality gate

**Files:** none (verification only).

**Why:** Validates that all code edits in Tasks 1, 5, and 6 didn't break anything, and that all doc edits in Tasks 2, 3, 4, 6 still build clean under `-W -n`. Equivalent of a final CI check before declaring the branch PR-ready.

- [ ] **Step 1: Strict docs build**

```bash
cd docs && rm -rf _build
SPHINXOPTS="-W --keep-going -n" uv run --extra docs sphinx-build -b html source _build/html
```

Expected: exit 0, zero warnings.

- [ ] **Step 2: Adapter unit tests**

```bash
uv run python -m pytest tests/knowledge_layer_tests/test_opensearch_adapter.py -q
```

Expected: all green.

- [ ] **Step 3: Reference YAML still parses**

```bash
uv run python -c "
import yaml
cfg = yaml.safe_load(open('configs/config_web_opensearch.yml'))
ks = cfg['functions']['knowledge_search']
assert ks['_type'] == 'knowledge_retrieval' and ks['backend'] == 'opensearch'
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Helm example values still parses**

```bash
uv run python -c "import yaml; yaml.safe_load(open('deploy/helm/examples/aws-opensearch-serverless-values.yaml'))"
```

Expected: no output.

- [ ] **Step 5: Branch summary**

```bash
git log --oneline develop..HEAD
echo "---"
git diff --shortstat develop..HEAD
```

Expected: a clean ordered list of commits, every one with a sign-off (verified in Task 7), the branch is ready to push to a fork and open a PR per CONTRIBUTING.md.

No commit needed — this is the final gate.

---

## Out of scope (folded into a future plan)

1. **Live TTL cleanup test.** Requires `AIQ_TTL_CLEANUP_INTERVAL_SECONDS` override and ~hour wall-clock or test-time injection. Worth a dedicated test fixture but not blocking PR mergeability.
2. **Full EKS deploy walkthrough.** The reference deployment doc is complete; the actual EKS-cluster-up validation is a separate effort the AWS team can drive once the PR lands.
3. **Multi-session concurrency / load.** AIQ's session-bound collection model creates many indexes in parallel under load. Worth a soak test before scaling beyond ~10 concurrent users on a single AOSS collection. Not a v2.0-launch blocker.
4. **Multimodal extraction parity.** Task 2 documents the gap. Closing it (adding `pdfplumber` tables, VLM image captions to OpenSearch ingestion the way LlamaIndex does it) is a feature-sized effort.
5. **Better Pydantic error for `OpenSearchAwsService`.** The current Pydantic Literal validation message is acceptable; not worth a custom error.
6. **Repo fork + push.** Pre-PR mechanical step — covered conversationally; no plan task needed.
