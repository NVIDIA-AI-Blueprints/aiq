# Tavily Web Fetch

A NeMo Agent Toolkit tool that opens exact web page URLs and returns extracted, line-numbered text. It complements
search tools by reading a known page rather than discovering pages from keywords.

## Configuration

No shipped config enables this tool, and that default is deliberate -- see [Security](#security).
Add the function block below and reference `fetch_url_tool` from a `data_source_registry` source
(so agents inherit it) or from an agent's explicit `tools` list.

```yaml
functions:
  fetch_url_tool:
    _type: tavily_web_fetch
    max_urls_per_call: 4
    max_chars_per_page: 10000
    max_chars_per_call: 24000
    extract_depth: advanced
    timeout_seconds: 30
```

The character limits are prompt-context budgets. Pages are extracted in full and then windowed locally. Set
`TAVILY_API_KEY` in the environment or provide `api_key` in config; without a key, the tool registers a stub that
returns an error string.

## Usage

Pass one or more complete HTTP(S) URLs. Use `query` to center the returned window on relevant text, or `start_line`
to continue a truncated page:

```text
urls=["https://example.com/report.pdf"], query="table 2.2"
```

Results contain one `<fetched_page>` section per URL. Of the sources this tool contributes, only successfully fetched
pages enter AI-Q's citation registry; soft 404s, failures, skipped pages, and outbound links in page content are not
registered as sources. This holds for the durable citation artifacts in the event stream as well as for the citation
registry, and depends on the configuration key chosen for the tool -- see
[Citation Scoping](#citation-scoping) below.

Long lines are wrapped when a page is read, and a window always contains whole lines. The truncation note therefore
reports exactly what was shown, and `start_line` reaches every character of the page.

## Security

This tool places full third-party web page content into the model context. It is disabled by
default, and enabling it is a deployment decision with security consequences. This section states
what the tool does and does not protect against so that decision can be made accurately. It is not
a claim that the tool is safe to enable in every deployment.

### Why This Tool Is Different from Search

Search tools return provider-selected excerpts: the page is chunked, reranked against the query,
and truncated before it reaches the model. That selection is itself a mitigation -- it bounds the
volume of untrusted text and how much attacker-controlled content survives ranking. Extraction
performs no selection and returns the page. In local testing the untrusted-text surface for a
single page was an order of magnitude larger than the same page seen through search chunks.

Setting `include_raw_content` on the search path returns byte-identical content to extraction, so
it is not a lighter-weight alternative to this tool.

### Trust Boundary

AI-Q never issues the outbound HTTP request. Every fetch goes through the extraction provider, and
there is no direct-HTTP fallback -- if extraction fails, the tool returns an error string to the
agent. The tool therefore cannot be used to make AI-Q itself reach an arbitrary address, but URL
and network policy belong to the provider rather than to AI-Q.

| Enforced by AI-Q | Delegated to the provider |
| --- | --- |
| URL scheme allowlist (`http`, `https`) | DNS resolution and outbound egress |
| `max_urls_per_call` | Redirect following |
| `max_chars_per_page`, `max_chars_per_call` | robots.txt, paywall, and authenticated-page handling |
| `timeout_seconds` | Refusal of private, loopback, or link-local addresses |
| Untrusted-content labelling and delimiting | Content filtering or moderation |
| Citation scoping | |

### What Is Not Validated

- **No domain allowlist or denylist.** Any `http(s)` URL the model produces is passed to the provider.
- **No private-address rejection in AI-Q.** `_validate_url` checks the scheme and network location
  only, so addresses such as `http://127.0.0.1/` or a cloud metadata endpoint pass AI-Q's
  validation. In testing the provider refused loopback, RFC1918, link-local, metadata, `file://`,
  and DNS rebinding hosts -- but that behavior is undocumented, may change, and could not be
  distinguished from a blocklist of well-known bypass domains. Treat the exposure as reduced rather
  than closed, and as inherited rather than owned.
- **No redirect re-validation.** Redirects are followed by the provider; the final URL is read back
  from the response and used as the citable source.
- **No content sanitization.** Content is compacted and windowed for length, not screened.
- **Character limits are prompt-context budgets, not download limits.** Pages are extracted in full
  and then windowed locally.

### Untrusted Content and Prompt Injection

Fetched page content is untrusted input and must never be treated as instructions. This is indirect
prompt injection: text on a page the agent reads can attempt to redirect the agent's behavior. It
is catalogued as LLM01, Prompt Injection, in the OWASP Top 10 for Large Language Model
Applications.

Injected text does not need to be visible to a human reader. In local testing HTML comments were
dropped during extraction, but text hidden with `display:none` and text carried in attributes such
as `title=` reached the output verbatim.

The provider documents no content filtering, moderation, or safety scoring on the extraction
endpoint, and its response exposes no safety signal a caller could inspect. Pages whose entire
subject was prompt injection and jailbreaking were returned in full and verbatim, with no warning.

No currently available mitigation eliminates this class of attack.

### Built-in Handling

Tool output labels retrieved content as untrusted, wraps each page in a `<fetched_page>` element
with HTML-escaped attributes, and numbers every line. This follows the standard practice of
segregating and identifying external content: it keeps a clear boundary between instructions and
retrieved data, and gives the model explicit provenance.

**These are prompt-level and bookkeeping measures, not an enforcement boundary.** They raise the
cost of an attack; they do not prevent one.

### Citation Scoping

Of the sources this tool contributes, only pages it actually read can be cited. Two independent
pipelines can turn a URL into a source, and both are addressed.

**The citation registry.** Each call records the pages it successfully read under the workflow run
that made the call, and the citation parser serves that run's record rather than re-reading the
result text -- so a tool name, a page reproducing this format, a concurrent workflow reusing the
same configuration key, and a replay of another run's result are all unable to add a source. A
call made outside a workflow run is not citable at all.

**The event stream.** AI-Q's event callback separately watches LangChain tool runs and writes
durable `citation_source` artifacts, which later seed follow-up jobs. It does not consult the
registry or the run record: it decides a tool produces URLs by testing its *name* for the
substrings `search`, `tavily`, `web_search`, `google`, and `bing`, then extracts every URL in the
raw result. The extraction adapter underneath this tool is named `tavily_extract` and returns whole
pages, so it is deliberately invoked without the surrounding run's callbacks and reports no tool
lifecycle of its own. The outer tool owns lifecycle reporting and decides its own citations.

**This depends on the configuration key you choose.** The key names the tool, and the substring
test above is applied to it. Naming the function block something like `tavily_fetch` or
`web_fetch_search` would make AI-Q treat the tool's own rendered output as search results and
scrape every URL in a fetched page -- outbound links included -- back into `citation_source`
artifacts. Use a key that contains none of those substrings; the documented example is
`fetch_url_tool`.

### Before You Enable This Tool

- Leave it disabled unless a workflow genuinely needs to read specific known pages.
- Do not enable it in the same agent as private or sensitive data sources without additional
  controls. Untrusted content, private data, and an outbound channel together are what turn an
  injection into a data loss event.
- Give the agent the smallest tool set that does the job. This tool is read-only; the impact of a
  successful injection is set by the other tools the agent can reach.
- Attach [Guardrails](../../docs/source/customization/guardrails.md) to screen retrieved content.
  Guardrails reduce opportunistic attacks and should not be relied on against a determined one.
- Consider a domain allowlist enforced in your own deployment. This is impractical for open-domain
  research but effective when the research domain is narrow.
- Treat whatever renders model output as the exfiltration sink: apply a content security policy,
  show links in full, and do not render obfuscated anchors.
- Keep `max_chars_per_page` and `max_chars_per_call` low. They bound untrusted text and token cost
  alike; agents that chain fetch calls can amplify usage quickly.
- Require human review before any high-risk action taken on the basis of fetched content.
- Test adversarially -- [garak](https://github.com/NVIDIA/garak) includes prompt injection probes.

Further reading: [Agentic Autonomy Levels and Security][agentic] and
[Four Ways to Deploy More Secure AI Agents][four-ways].

### Provider Considerations

Extraction is performed by the Tavily Extract API. The tool shares `TAVILY_API_KEY` -- and
therefore the account, quota, and terms of service -- with `tavily_web_search`.

Only URLs are sent to the provider. The `query` argument selects which part of a long page to show
and is deliberately never forwarded, so user query text does not leave AI-Q through this tool.

The URLs an agent fetches, and the content returned for them, transit third-party infrastructure.
Review the provider's published data retention, privacy, and model-training terms for your own
account and contract; terms negotiated by anyone else do not apply to your deployment.

### Secrets, Logging, and Telemetry

The API key is held as a `SecretStr` and read from `TAVILY_API_KEY` when not set in config. Without
a key the tool registers a stub that returns an error string, so a missing secret degrades
gracefully instead of crashing.

**This module's Python logger** records the exception class name only on an extraction failure --
never the key, the URL, or page content.

**That is not the whole logging contract.** The requested URL and the content returned to the model
leave this module through two channels this tool does not control. AI-Q's job event stream records
the requested URL on the tool-start event and persists it for the job. NeMo Relay records more: its
`enable_full_payloads` defaults to `true`, and ATOF export defaults to `enabled: true` with
`mode: append`, so a trace retains both the complete requested URL and the entire content returned
to the model. The `relay` block is attached to every workflow by default, so this applies even to a
config that has no `relay` section. Assume the URL and the page text are stored, and are exported
anywhere Relay is configured to export.

**Do not let this tool receive credential-bearing URLs.** It accepts any `http(s)` URL the model
produces, which can include signed download URLs, query-string credentials or tokens, internal
document identifiers, and user-identifying paths. Relay's built-in detectors cover common
credential and personal-data shapes; they are not guaranteed to recognize an arbitrary signed-URL
token, and a redacted payload is not a guarantee that nothing sensitive survived.

Two of the supported controls are deployment-level, in the workflow's `relay` block; the one that
actually removes this data is per-request.

| Control | Where | Effect on the URL and page content |
| --- | --- | --- |
| `observability.atof.enabled: false` | workflow `relay` block | No ATOF trace file is written, so nothing is retained locally. |
| `observability.opentelemetry.enabled: false` (the default) | workflow `relay` block | Traces are not sent to an external collector. |
| `x-aiq-telemetry-redact: true` | request header | Both are removed from the trace before export. |

**Request privacy is activated by the request, not by configuration.** Send
`x-aiq-telemetry-redact: true` with the request; AI-Q turns that header into a trace tag that
switches Relay payload sanitization on for the life of the request. `redaction.request_privacy_attributes`
only selects which scope attributes are cleared once it is already active -- editing that list
enables nothing on its own. The sanitizers are registered only when `redaction.enabled` is `true`,
so setting `redaction.enabled: false` silently disarms the header too.

**`enable_full_payloads: false` does not remove them.** It reads like the control for this, and is
documented generally as preserving inputs and outputs for export, but AI-Q hands tool payloads to
Relay as explicit scope values that the setting does not govern. With it disabled, the requested
URL and the returned page content are still present in the trace. Do not rely on it here.

ATOF appends to a JSONL file that is not rotated or pruned, so it accumulates URLs and page text
for the life of the deployment. Auditing that file's access controls and retention, and those of
every configured export destination, is the operator's responsibility. See
[Redaction and privacy](../../docs/source/deployment/observability.md) for the system-wide picture.

### Reporting a Vulnerability

Report security issues through the process in [SECURITY.md](../../SECURITY.md). Do not open a
GitHub issue for a security report.

[agentic]: https://developer.nvidia.com/blog/agentic-autonomy-levels-and-security/
[four-ways]: https://developer.nvidia.com/blog/four-ways-to-deploy-more-secure-ai-agents
