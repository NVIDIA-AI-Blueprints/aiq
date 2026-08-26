# You.com Tools

NAT-based tools for the You.com API. Requires a `YDC_API_KEY` environment variable or `api_key` config.
Create an API key, claim your free credits, and learn more at https://you.com/docs/quickstart.

## Tools

### `you_web_search`

Retrieves relevant search results from the web using You.com [Web Search](https://you.com/docs/api-reference/search/v1-search-post). Supports livecrawl (full page content),
freshness filtering, safesearch, and news filtering.

The [Web Search](https://you.com/docs/api-reference/search/v1-search-post) endpoint is designed to return LLM-ready web
results based on a user’s query. Based on a classification mechanism, it can return web results and news associated with
your query. If you need to feed an LLM with the results of a query that sounds like What are the latest geopolitical
updates from India, then this endpoint is the right one for you.

Key config:
- `max_results` — number of results (1–100, default 10)
- `safesearch` - `off`, `moderate`, `strict`
- `livecrawl_mode` — `off`, `web`, `news`, `all` (default `web`)
- `livecrawl_format` — `off`, `markdown`, `html` (default `markdown`)
- `freshness` — `off`, `day`, `week`, `month`, `year`
- `max_content_length` — truncate livecrawl content to reduce token usage (default 50000, `None` for unbounded)
- `include_news_results` — True/False whether or not you want to include results categorized as `news`

### `you_research`


[Research](https://you.com/docs/api-reference/research/v1-research) goes beyond a single web search. In response to your
question, it runs multiple searches, reads through the sources, and synthesizes everything into a thorough, well-cited
answer. Use it when a question is too complex for a simple lookup, and when you need a response you can actually trust
and verify.

Key config:
- `research_effort` — `lite`, `standard` (default), `deep`, `exhaustive`

### `you_finance_research`

The [Finance Research API](https://you.com/docs/api-reference/finance-research/v1-finance_research) is purpose-built
for financial questions. Like the Research API, it runs multiple searches, reads through sources, and synthesizes
everything into a thorough, well-cited answer — but its retrieval index is optimized for financial data: earnings
reports, SEC filings, analyst coverage, market data, and financial news. Use it when you need credible, sourced answers
to financial questions: company fundamentals, market trends, competitive analysis, earnings summaries, or macroeconomic research.

Key config:
- `research_effort` — `deep` (default) or `exhaustive` only

### `you_contents`

Extracts clean page content from URLs using the You.com [Contents API](https://you.com/docs/api-reference/contents).
Pass up to 10 URLs and receive their full content — no HTML parsing required.

Key config:
- `formats` — list of `markdown`, `html`, `metadata` (default `["markdown", "metadata"]`)
- `crawl_timeout` — per-URL crawl timeout in seconds (1–60); increase for JavaScript-heavy pages

We want to hear from you. If you hit a configuration issue or have questions, reach out to us at support@you.com.
For enterprise or private inquiries, reach out to api@you.com.
