# Reranked Search Source

A reranking layer over multiple search tools for NeMo Agent Toolkit workflows. Fans out a query to configured search tools in parallel, reranks them by relevance, and filter top k results.

## How It Works
1. The reranker receives a query from the agent
2. Calls all `search_tools` in parallel with the same query
3. Scores and ranks all results across sources using the cross-encoder reranking model
4. Returns the top-k results to the agent

## Environment Variables

By default, reranker is invoked from nvidia.build.com and requires NVIDIA_API_KEY to run model inference:

```bash
NVIDIA_API_KEY=your_nvidia_api_key
```

## Example Workflow Configuration

Define the reranked_search tool and other search tools that feed into the reranker. If the search tools are part of a function group, they must be specified in the group's `- include:` list, and use `{group_name}__{tool_name}` format in `reranked_search` config section.

For more info on function group name space, reference Nemo Agent Toolkit doc, specifically [Function Naming and Namespaing](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/functions-and-function-groups/function-groups.html#function-naming-and-namespacing) and [Understanding Function Accessibility](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/functions-and-function-groups/function-groups.html#understanding-function-accessibility).

```yaml
function_groups:
  your_group:
    _type: your_group
    include: [tool_1, tool_2]
    ...

functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5

  your_custom_search_tool:
    _type: your_custom_search
    ...

  reranked_search:
    _type: reranked_search
    # required configs
    cross_encoder_model: nv-rerank-qa-mistral-4b:1
    search_tools:
      - web_search_tool # standalone function examples
      - your_custom_search_tool
      - your_group__tool_1 # function group examples
      - your_group__tool_2

    # # uncomment to adjust default values
    # top_k: 5  # adjust as necessary as you add more search tools, meaning more results to rerank.
    # timeout_seconds: 10 # per-tool timeout
```

Then give it to an agent as its only tool:

```yaml
  shallow_research_agent:
    _type: shallow_research_agent
    llm: nemotron_nano_llm
    tools:
      - reranked_search
```

See `sources/reranker/example_cli_config.yml` for a full working example.

### Supported Reranker Models
Choose any rerank model from build.nvidia.com

## Make Your Source Compatible with Reranker
All built-in sources under `./sources` folder are already supported.

To design a new source that supports reranking, there's only one condition:
*  use `aiq_agent.common.SOURCE_DELIMITER` to join all the search result strings returned by your tool. The reranker tool will use the same delimiter to break down the long string into seperate sources and rerank them by relevance.
