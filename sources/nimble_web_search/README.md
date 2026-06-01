# Nimble Web Search

NAT-based [Nimble](https://nimbleway.com/) web search tool for agentic search workflows that need live web context. Requires a `NIMBLE_API_KEY` environment variable or `api_key` config.

## When to use

Use `nimble_web_search` when your AI-Q agent needs fresh web context from Nimble's real-time web intelligence infrastructure. The provider is designed for agentic search workflows that benefit from live web discovery, structured results, and reliable retrieval through Nimble's search layer.

Choose `nimble_web_search` when Tavily or Exa are not the right fit for your workflow, or when you want to standardize web-search retrieval through Nimble. The provider follows the same integration pattern as `exa_web_search` and `tavily_web_search`, making it straightforward to configure as an alternative search backend in AI-Q.

## Install

This package is installed automatically by `scripts/setup.sh` alongside the other data-source plugins. Manual install:

```bash
uv pip install -e ./sources/nimble_web_search
```

## Configure

Add a `nimble_web_search` function to your workflow YAML:

```yaml
functions:
  web_search_tool:
    _type: nimble_web_search
    max_results: 5
    search_depth: lite
    country: US
    locale: en
```

See [`docs/source/customization/configuration-reference.md`](../../docs/source/customization/configuration-reference.md) for the full parameter table.

## Environment

```bash
NIMBLE_API_KEY=...
```

You can alternatively set `api_key` directly in the YAML (as a string). Both paths use the standard `nat.data_models.function.FunctionBaseConfig` `SecretStr` handling — the key is not logged.

## Test

```bash
# Unit tests (credential-free, mocked)
uv run pytest sources/nimble_web_search -v

# Lint
uv run ruff check sources/nimble_web_search
uv run ruff format --check sources/nimble_web_search
```

The unit tests cover: config defaults / all fields / invalid `search_depth` rejection, missing-key stub + warn-once, key-from-config env hydration, successful render + description fallback, deep depth passthrough, query/content truncation, empty/error handling, retry-then-success, final-retry failure, 401, 403 enterprise-tier, non-default country/locale passthrough, and renderer behavior on titles containing special characters.

## Verification

Beyond the mocked unit tests above, verify the provider is fully integrated with AI-Q by walking the [adding-a-data-source checklist](../../docs/source/extending/adding-a-data-source.md):

```bash
# 1. Mocked unit tests pass (CI-safe, no credentials)
uv run pytest sources/nimble_web_search -q
# → 21 passed in <1s

# 2. NAT discovers the registered function
nat info components --types function | grep nimble_web_search
# → nimble_web_search 1.0.0 function

# 3. Lint, format, and dependency lock all clean
uv run ruff check sources/nimble_web_search
uv run ruff format --check sources/nimble_web_search
uv lock --check

# 4. Live smoke through any workflow that names `_type: nimble_web_search` (requires NIMBLE_API_KEY)
export NIMBLE_API_KEY=...
nat run --config_file <your-workflow.yml> --input "your test query"
```

Step 4 satisfies the checklist's "Installed and tested with `nat run`" item. Any of the existing AI-Q web search configs (`configs/config_cli_default.yml`, `configs/config_web_default_llamaindex.yml`, etc.) becomes a Nimble-backed test by swapping `_type: tavily_web_search` → `_type: nimble_web_search` and translating `advanced_search: true` → `search_depth: deep`.

## Native capabilities

The provider exposes the following Nimble-specific surface. Defaults are tuned for the common AI-Q research workflow (lite-mode SERP for a few results, US/English regional bias):

| Capability | Field | Default | Notes |
|---|---|---|---|
| Result count | `max_results` | `5` | Range `1-100` (Nimble's documented cap). Soft cap (Nimble may return up to N+2; see Known limitations). |
| Search depth | `search_depth` | `lite` | See the dedicated [Search depth](#search-depth) section below. |
| Search focus | `focus` | `general` | Nimble focus mode: `general` (default, broad web/research), `news` (current events), or domain-specific `location` / `shopping` / `geo` / `social`. Leave `general` for normal research; the LLM never selects focus, so general queries can't drift to `news`. |
| Localization — country | `country` | `US` | Two-letter country code (e.g. `FR`, `JP`, `UK`). Reaches the SDK constructor verbatim. |
| Localization — language | `locale` | `en` | ISO 639-1 language code (e.g. `fr`, `ja`). |
| Per-result content size | `max_content_length` | `10000` chars | Truncates each result's body to N chars (3-char ellipsis included). Minimum `1`; set to `null` to disable truncation; omit to use default. |
| Retries | `max_retries` | `3` | Exponential backoff on transient errors. Final failure surfaces a friendly per-status message (401, 403, generic). |
| Auth | `api_key` / `NIMBLE_API_KEY` | env or config | `pydantic.SecretStr`; never logged. Config-side `api_key` hydrates the env var so the underlying SDK can read it. |

Each `<Document>` block in the rendered output carries an `entity_type` (`"OrganicResult"` for SERP results). The `include_answer=True` capability — which would produce an `entity_type="answer"` block first — is intentionally **not exposed** in this initial integration. See [Known limitations](#known-limitations).

## Search depth

| Value | Behavior | Account requirement |
|---|---|---|
| `lite` (default) | Metadata only — URL, title, description. Token-efficient. | Any |
| `fast` | Enterprise tier. Lower latency, richer content. | **Enterprise account required.** Returns a 403 ToolException with `"search_depth='fast' is not enabled for this account. Contact sales for access."` on non-enterprise accounts. |
| `deep` | Higher token cost. May return short page-content snippets in addition to metadata. | Any (in this account; behavior may vary by tier) |

If you do not know your tier, leave `search_depth: lite` and let the description field carry the content.

## Known limitations

- `max_results` is a **soft cap**. The Nimble API may return up to N+2 documents when asked for N. The provider returns them all; AI-Q's downstream consumers can slice if they need a hard cap.
- `lite` mode returns `page_content == ""` per result. The provider falls back to `description` (~150 chars per result, organic-result quality).
- `include_answer` is **not exposed** in this initial integration. It can be added in a follow-up.

## Security

- API key handling follows the existing `EXA_API_KEY` / `TAVILY_API_KEY` pattern: env var or `SecretStr` config; never logged.
- Untrusted API fields (`url`, `title`, body) are HTML-escaped before being rendered into the `<Document>` markup, so a result can't break the block or inject into downstream parsers.
- Tests are mocked; no live network in CI.
- The optional live smoke is documented in the PR description and uses a redacted output pattern.
