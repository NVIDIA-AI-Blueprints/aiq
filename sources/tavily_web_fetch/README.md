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
registered as sources.

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
retrieved data, and gives the model explicit provenance. Of the sources this tool contributes, only
pages it actually read can be cited: its citation parser claims a result only when the result opens
with the preamble above, and within that result only successfully fetched pages are registered.

**These are prompt-level and bookkeeping measures, not an enforcement boundary.** They raise the
cost of an attack; they do not prevent one.

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

### Secrets and Logging

The API key is held as a `SecretStr` and read from `TAVILY_API_KEY` when not set in config. Without
a key the tool registers a stub that returns an error string, so a missing secret degrades
gracefully instead of crashing. Extraction failures log the exception class name only -- never the
key, the URL, or page content.

### Reporting a Vulnerability

Report security issues through the process in [SECURITY.md](../../SECURITY.md). Do not open a
GitHub issue for a security report.

[agentic]: https://developer.nvidia.com/blog/agentic-autonomy-levels-and-security/
[four-ways]: https://developer.nvidia.com/blog/four-ways-to-deploy-more-secure-ai-agents
