# Troubleshooting for AI-Q NVIDIA Research Assistant Blueprint

The software components in the blueprint interact in the following way:

![architecture](/docs/images/aira-service-architecture.png)

Start troubleshooting by narrowing down which sub-service is failing. The first step is to determine if the UI is misconfigured, the middleware proxy, or the backend. We also recommend following the RAG blueprint documentation to ensure RAG is fully functional prior to deploying the AI-Q Research Assistant.

## Errors with Collections or Document Upload

To identify errors with collections or document upload, follow the steps below.

1. Attempt to list the collections directly through the RAG `ingestor-server` API:

    ```bash
    # replace ingestor-server with the *PUBLIC* IP address of your rag service, or run this command from a container
    curl -v http://ingestor-server:8082/v1/collections
    ```

    If this doesn't work, follow the RAG documentation to fix the deployment. Check the ingestor-server logs, eg `docker logs ingestor-server -f`. 

2. Attempt to list the collections through the backend service:

    ```bash
    # replace aira-backend with the *PUBLIC* IP address of the backend service, `localhost`, or run this command from a container 
    curl -v http://aira-backend:3838/v1/collections
    ```

    If this doesn't work, check the backend configuration and ensure `RAG_INGEST_URL` is properly set. Check the backend logs, eg `docker logs aira-backend -f`. 


3. Attempt to list the collections through the application. Check the browser network logs and the application logs, `docker logs aira-frontend -f`. If this does not work, ensure you have configured the application via the `INFERENCE_ORIGIN` environment variable which should be set to the IP address of your backend service, `http://aira-backend:3838`. 

4. If collection listing works, but documents fail to upload, check the logs in the RAG ingestor service, `docker logs ingestor-server -f`. 

**Note: During bulk file upload using the file upload utility, if you see 429 errors in the logs for the compose-nv-ingest-ms-runtime-1 service log it suggests a temporary error. You can re-run the file upload command multiple times, each time the process will pick up where it left off, uploading any documents that failed due to this error.**

### Known Issue: Large Bulk Ingestion Failure using MIG 

For MIG support, currently the ingestion profile has been scaled down while deploying the chart with MIG slicing. This affects the ingestion performance during bulk ingestion, specifically large bulk ingestion jobs might fail.

For additional known issues related to the RAG Blueprint, see the [CHANGELOG](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/CHANGELOG.md#all-known-issues).

## Errors with Report Plan Generation 

To identify errors with Rreport planning generation, follow the steps below.

1. Attempt to connect to the AI-Q Research Assistant backend API. In a browser, navigate to http://aira-backend:3838/docs, replacing `<aira-backend>` with the *PUBLIC* IP address of the AI-Q Research Assistant service or `localhost`. Use the API docs to run the `/generate_query`. If the docs do not load, check the AI-Q Research Assistant services logs `docker logs aira-backend -f`. 

2. If the docs load, but the example API request fails or the UI stalls after saying "Generating queries", the issue will likely be with the `nemotron` model configuration in the AI-Q Research Assistant configuration file. Verify this model configuration is correct, and attempt to make a sample request directly to the LLM. Example requests are provided on `build.nvidia.com`.


## Errors with Q&A

To identify errors with Q&A, follow the steps below.

1. Attempt to connect to the AI-Q Research Assistant backend API. In a browser, navigate to http://aira-backend:3838/docs, replacing `<aira-backend>` with the *PUBLIC* IP address of the AI-Q Research Assistant service or `localhost`. Use the API docs to run the `/artifact_qa` call. If the docs do not load, check the AI-Q Research Assistant services logs `docker logs aira-backend -f`. 

2. If the docs load, but the example API request fails or the UI stalls after showing "AIQ Thinking", the issue is likely with the `instruct_llm` model configuration in the AI-Q Research Assistant configuration file. Verify this model configuration is correct, and attempt to make a sample request directly to the LLM. Example requests are provided on https://build.nvidia.com.

## Errors with RAG Search During Report Generation

Ensure you have appropriately configured the `rag_url` settings in the AI-Q Research Assistant configuration file, or provided appropriate values in the helm `values.yaml` file.

If you are using one of the default report topics and prompts, ensure you have [loaded the default collections](./get-started/get-started-docker-compose.md#add-default-collections).

## Errors with Web Search During Report Generation

Ensure you have provided a valid Taviliy API key, and have set the `TAVILY_API_KEY` environment variable.

## Model Download Issues

### Known Issue: Model Download Error

**Issue**: When deploying `llama-3.3-70b-instruct`, you may encounter download errors with "Too many open files" messages. This is a known issue documented in the [NVIDIA NIM 1.13.0 Release Notes](https://docs.nvidia.com/nim/large-language-models/1.13.0/release-notes.html).

**Workarounds**:
1. **Increase file descriptor limits**: Add `--ulimit nofile=65536:65536` to your Docker run command
2. **Retry the deployment**: Sometimes the download succeeds on subsequent attempts  
3. **Pin to an earlier version**: As a last resort, use a specific working version from the [NGC catalog](https://catalog.ngc.nvidia.com/orgs/nim/teams/meta/containers/llama-3.3-70b-instruct?version=1.14.0):
   ```yaml
   # In docker-compose.yaml
   image: nvcr.io/nim/meta/llama-3.3-70b-instruct:1.14.0
   ```

## Checking Model Profiles

You can check available profiles for your system to ensure compatibility and optimal performance:

### Llama 3.3 70B Instruct Profiles

```bash
# List available profiles for Llama 3.3 70B Instruct
docker run --rm --gpus=all -e NGC_API_KEY=$NGC_API_KEY \
  nvcr.io/nim/meta/llama-3.3-70b-instruct:1.14.0 \
  list-model-profiles
```

### Nemotron Model Profiles

For the Nemotron model used by RAG (running in the `nim-llm-ms` container), you can check its profiles after the RAG deployment is complete:

```bash
# Check profiles for the already-running Nemotron model in nim-llm-ms container
docker exec nim-llm-ms list-model-profiles
```

### Hardware Requirements Reference

- **Llama 3.3 70B Instruct**: See detailed hardware requirements and optimization profiles in the [NVIDIA NIM Supported Models documentation](https://docs.nvidia.com/nim/large-language-models/1.13.0/supported-models.html#llama-33-70b-instruct)
- **Llama 3.3 Nemotron Super 49B**: For supported hardware configurations, see the [Nemotron documentation](https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html#llama-3-3-nemotron-super-49b-v1-5)

**Note**: Profiles help ensure optimal performance and resource utilization. The system will automatically select the most appropriate profile based on your hardware configuration.
