# Brave Web Search

NAT tool package for the Brave Search API web search endpoint.

## Configuration

```yaml
functions:
  web_search_tool:
    _type: brave_web_search
    max_results: 5
    country: US
    search_lang: en
```

Set `BRAVE_API_KEY` in the environment, or provide `api_key` in the workflow config.
