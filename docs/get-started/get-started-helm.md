<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Get Started with AI-Q NVIDIA Research Assistant Blueprint Helm Deployment

This guide provides instructions for deploying the NVIDIA AI-Q Research Assistant blueprint using Helm on a Kubernetes cluster.

## Prerequisites 


1. A NGC API key that is able to access the AI-Q blueprint images. A key can be generated at https://org.ngc.nvidia.com/setup/api-keys. For **Services Included**, select **NGC Catalog** and **Public API Endpoints**.
2. Kubernetes and Helm with [NVIDIA GPU Operator installed](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/getting-started.html#operator-install-guide). This helm chart was tested on [Cloud Native Stack](https://github.com/NVIDIA/cloud-native-stack?tab=readme-ov-file)
3. [Optional] A Tavily API key to support web search.

## Hardware Requirements

The AI-Q Research Assistant blueprint requires the deployment of the NVIDIA RAG blueprint. To deploy both blueprints using Helm requires the following hardware configurations:

| Option | RAG Deployment | AIRA Deployment | Total Hardware Requirement |
|--------|----------------|-----------------|---------------------------|
| Single Node - MIG Sharing | [Use MIG sharing](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/mig-deployment.md) | [Default Deployment](#deploy-the-ai-q-research-assistant) | 4 x H100 80GB for RAG<br/>2 x H100 80GB for AIRA<br/> |
| Multi Node | [Default Deployment](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-helm.md) | [Default Deployment](#deploy-the-ai-q-research-assistant) | 8 x H100 80GB for RAG<br/>2 x H100 80GB for AIRA<br/>---<br/>9 x A100 80GB for RAG<br/>4 x A100 80GB for AIRA<br/>---<br/>9 x B200 for RAG<br/>2 x B200 for AIRA<br/>---<br/>8 x RTX PRO 6000 for RAG<br/>2 x RTX PRO 6000 for AIRA |

> **Note:** Mixed MIG support requires GPU operator 25.3.2 or higher and NVIDIA Driver 570.172.08 or higher.

## Deployment

### Deploy RAG

Follow the [NVIDIA RAG blueprint Helm deployment guide](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-helm.md).

### Deploy the AI-Q Research Assistant

#### Set environment variables

```bash
export NGC_API_KEY="<your-ngc-api-key>"
export TAVILY_API_KEY="<your-tavily-api-key>"
```

#### Clone the repo

```bash
git clone https://github.com/NVIDIA-AI-Blueprints/aiq-research-assistant
```

#### Navigate to the helm chart directory

```bash
cd aiq-research-assistant/deploy/helm
```

#### Create a namespace for AIQ helm chart

```bash
kubectl create namespace aiq
```

#### Deploy the chart

To deploy pre-built chart from NGC:

```bash
helm install aiq-aira https://helm.ngc.nvidia.com/nvidia/blueprint/charts/aiq-aira-v1.2.0.tgz \
--username='$oauthtoken'  \
--password=$NGC_API_KEY \
--set imagePullSecret.password=$NGC_API_KEY \
--set ngcApiSecret.password=$NGC_API_KEY \
--set tavilyApiSecret.password=$TAVILY_API_KEY -n aiq
```

To deploy from source:

```bash
helm install aiq-aira aiq-aira/ \
--set imagePullSecret.password=$NGC_API_KEY \
--set ngcApiSecret.password=$NGC_API_KEY \
--set tavilyApiSecret.password=$TAVILY_API_KEY -n aiq
```

The deployment commands above assume the RAG deployment instructions were followed in [Deploy RAG](#deploy-rag) with the RAG services running in the `rag` namespace. If using a different RAG deployment, the default service URLs can be overridden by setting `backendEnvVars.RAG_SERVER_URL` and `backendEnvVars.RAG_INGEST_URL`. For example:

```bash
helm install aiq-aira aiq-aira/ \
--set imagePullSecret.password=$NGC_API_KEY \
--set ngcApiSecret.password=$NGC_API_KEY \
--set tavilyApiSecret.password=$TAVILY_API_KEY \
--set backendEnvVars.RAG_SERVER_URL=<RAG_SERVER_URL> \
--set backendEnvVars.RAG_INGEST_URL=<INGESTOR_SERVER_URL> -n aiq
```

##### Deploy with NIM Operator 

The [NVIDIA nim-operator 3.0 and above](https://docs.nvidia.com/nim-operator/latest/install.html) must also be installed and configured in your cluster to ensure that the Nvidia NIM LLM is properly deployed.

```bash
helm install aiq-aira aiq-aira/ \
--username='$oauthtoken'  \
--password=$NGC_API_KEY \
--set imagePullSecret.password=$NGC_API_KEY \
--set ngcApiSecret.password=$NGC_API_KEY \
--set tavilyApiSecret.password=$TAVILY_API_KEY \
--set nim-llm.enabled=false \
--set backendEnvVars.INSTRUCT_MODEL_NAME="meta/llama-3.3-70b-instruct" \
--set nimOperator.enabled=true -n aiq
```

Use the below command to download the specfic NIM LLM Profile with NIM Operator

Example: 
```bash
helm install aiq-aira aiq-aira/ \
  --set imagePullSecret.password=$NGC_API_KEY \
  --set ngcApiSecret.password=$NGC_API_KEY \
  --set tavilyApiSecret.password=$TAVILY_API_KEY \
  -f values-nim-operator.yaml -n aiq
```

#### Instruct LLM profile selection

By default, the deployment of the instruct LLM attempts to automatically select the most suitable profile from the list of compatible profiles based on the detected hardware. Because of a known issue, vllm-based profiles are selected, so we recommend that you manually select a tensorrt_llm profile before you start the nim-llm service. 

You can list available profiles by running the NIM container directly:
```bash
USERID=$(id -u) docker run --rm --gpus all \
  nvcr.io/nim/meta/llama-3.3-70b-instruct:1.13.1 \
  list-model-profiles
```

Using the list of model profiles from the previous step, set the NIM_MODEL_PROFILE in the `nim-llm` section of the [values.yaml](../../deploy/helm/aiq-aira/values.yaml). It is ideal to select one of the tensorrt_llm profiles for best performance. Here is an example of selecting one of these profiles for two H100 GPUs:
```
env:
 - name: NIM_MODEL_PROFILE
   value: "tensorrt_llm-h100-fp8-tp2-pp1-throughput-2330:10de-bedaf1e0ba87272295f4fcb590e781436120751026098f448fd8bc4d711ba5d7-4"
```

If using A100s, the `nim-llm` section will also have to be updated to allocate four GPUs instead of two:
```
resources:
  limits:
    nvidia.com/gpu: 4
  requests:
    nvidia.com/gpu: 4
```

##### Hardware-Specific Profiles

The following tensorrt_llm profiles are optimized for different common GPU configurations:

###### 2xH100 NVL
```
tensorrt_llm-h100_nvl-fp8-tp2-pp1-throughput-2321:10de-5e20634213cb4c32e86f048dbc274eb8bff74720af81fe400d8924e766f3e723-4
```

###### 2xH100 SXM
```
tensorrt_llm-h100-fp8-tp2-pp1-throughput-2330:10de-bedaf1e0ba87272295f4fcb590e781436120751026098f448fd8bc4d711ba5d7-4
```

###### 4xA100
```
tensorrt_llm-a100-bf16-tp4-pp1-throughput-20b2:10de-8dfffd86cd28a6ea7086f8d3d33f0d60c66df738652cea44c722766b77508b5c-4
```

###### 2xRTX PRO 6000
```
tensorrt_llm-rtx6000_blackwell_sv-nvfp4-tp2-pp1-latency-2bb5:10de-b5d32ce12a99b422e2c5a9a772bfd29493467cd5f22248ed936e2d43c5747771-2
```

###### 2xB200
```
tensorrt_llm-b200-bf16-tp2-pp1-latency-2901:10de-d89dfd90f9f326864bc6051f45b5aca8e758fdb009b1da43d93b1d5a2236026e-2
```

More information about model profile selection can be found [here](https://docs.nvidia.com/nim/large-language-models/latest/profiles.html#profile-selection) in the NVIDIA NIM for Large Language Models (LLMs) documentation.

#### Check status of pods
```bash
kubectl get pods -n aiq
```

Response should look like this:
```
NAME                                      READY   STATUS             RESTARTS       AGE
aiq-aira-aira-backend-5797589756-td5b2    1/1     Running            0              5m
aiq-aira-aira-frontend-74ff7cc5c8-wf9jx   1/1     Running            0              5m
aiq-aira-nim-llm-0                        1/1     Running            0              5m
aiq-aira-phoenix-78fd7584b7-s9bwc         1/1     Running            0              5m
```

#### Access to UI

Since the frontend service has a `nodePort` configured for port 30080, you can view the UI from a web browser on the host running `kubectl` at http://localhost:30080.

The UI can also be viewed from outside the cluster at: `http://<cluster-node-name-or-ip>:30080`


## Create Default Collections

The AI-Q NVIDIA Research Assistant demo web application requires two default collections. One collection supports a biomedical research prompt and contains reports on Cystic Fibrosis. The second supports a financial research prompt and contains public financial documents from Alphabet, Meta, and Amazon.

Follow the steps in [Bulk Upload via Python](../../data/readme.md#bulk-upload-via-python) to create these default collections.

## Stopping Services

To stop all services, run the following commands:

1. Delete the AIRA deployment:
```bash
helm delete aiq-aira -n aiq
```
  1a. Delete the NIM Operator Cache if it's been used above
  ```bash
  kubectl delete nimcache meta-llama3-70b-instruct -n aiq
  ```

2. Delete the RAG deployment:
```bash
helm delete rag -n rag
```

3. Delete the namespaces:
```bash
kubectl delete namespace aiq
kubectl delete namespace rag
```
