# Google Scholar Paper Search

A NeMo Agent Toolkit function that searches for academic papers using Google Scholar through the Serper API.

## Prerequisites

Before using this function, you need a Serper API key:

1. Go to [serper.dev](https://serper.dev/) and create an account
2. Generate an API key from your dashboard
3. Add the API key to your `deploy/.env` file in the project root:

```bash
SERPER_API_KEY="your-serper-api-key"
```

Alternatively, you can provide the API key directly in the configuration file (see below).

## Installation

Install the package using `uv` from the project root:

```bash
uv pip install -e sources/google_scholar_paper_search
```

After installation, verify the plugin is registered:

```bash
nat info functions | grep paper_search
```

## Configuration

### Adding the Function

Add the `paper_search` function to the `functions` section of your workflow configuration file:

```yaml
functions:
  paper_search_tool:
    _type: paper_search
    max_results: 10
    timeout: 30
    serper_api_key: ${SERPER_API_KEY}
```

#### Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_results` | integer | 10 | Maximum number of search results to return (capped at 50) |
| `timeout` | integer | 30 | Timeout in seconds for search requests |
| `serper_api_key` | string | None | Serper API key (can also be set through the `SERPER_API_KEY` environment variable) |

### Adding as a Tool to an Agent

After defining the function, add it to the `tools` list of any agent that should use paper search capabilities:

```yaml
functions:
  paper_search_tool:
    _type: paper_search
    max_results: 5
    serper_api_key: ${SERPER_API_KEY}

  my_research_agent:
    _type: shallow_research_agent
    llm: my_llm
    tools:
      - paper_search_tool
    max_llm_turns: 10
```

### Complete Example

Here is a complete configuration example showing how to integrate the paper search tool:

```yaml
llms:
  my_llm:
    _type: nim
    model_name: nvidia/nemotron-3-nano-30b-a3b
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.7

functions:
  paper_search_tool:
    _type: paper_search
    max_results: 10
    serper_api_key: ${SERPER_API_KEY}

  web_search_tool:
    _type: tavily_internet_search
    max_results: 5

  deep_research_agent:
    _type: deep_research_agent
    llm: my_llm
    report_llm: my_llm
    max_loops: 2
    tools:
      - paper_search_tool
      - web_search_tool

workflow:
  _type: chat_deepresearcher_agent
```

## Usage

The paper search function accepts the following arguments when called by an agent:

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `query` | string | Yes | The search query for finding academic papers |
| `year` | string | No | Year or year range filter (for example, "2023" or "2020-2023") |
| `source` | string | No | Search source (defaults to "serper") |

## Troubleshooting

### Common Issues

**API key not found**

If you see an error about the API key not being found:

- Verify the `SERPER_API_KEY` environment variable is set correctly
- Alternatively, ensure the `serper_api_key` is specified in the configuration file

**Request timeout**

If searches are timing out:

- Increase the `timeout` value in the configuration
- Check your network connection

**No results returned**

If no papers are found:

- Try a broader search query
- Remove year filters to expand the search range
- Verify your Serper API key has available quota

## Disabling Paper Search

If you don't have a Serper API key or don't need paper search functionality, you can disable it by removing the tool from your configuration:

### Remove from Configuration

Edit your configuration file (for example, `configs/config_cli_default.yml`) and remove or comment out the `paper_search_tool` definition:

```yaml
functions:
  # Remove or comment out this section
  # paper_search_tool:
  #   _type: paper_search
  #   max_results: 5
  #   serper_api_key: ${SERPER_API_KEY}
```

Also remove it from any agents that use it:

```yaml
functions:
  deep_research_agent:
    _type: deep_research_agent
    orchestrator_llm: nemotron_llm
    max_loops: 2
    tools:
      # Remove paper_search_tool from the tools list
      - advanced_web_search_tool
```

After making these changes, the agent will function without paper search capabilities.
