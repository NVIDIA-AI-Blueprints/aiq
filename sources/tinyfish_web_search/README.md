# TinyFish Web Search

NAT tool package for the TinyFish Search API.

## Configuration

```yaml
functions:
  web_search_tool:
    _type: tinyfish_web_search
    max_results: 5
    location: US
    language: en
```

Set `TINYFISH_API_KEY` in the environment, or provide `api_key` in the workflow config.
