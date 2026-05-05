<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Amazon OpenSearch Serverless

AI-Q can use the built-in OpenSearch knowledge backend with Amazon OpenSearch Serverless vector collections. The backend
uses SigV4 service `aoss`, creates one OpenSearch index per AI-Q collection/session, and supports Dask ingestion workers
by creating the OpenSearch client inside the worker process.

```{note}
**Migrating from AI-Q v1.0.** On v1.0, OpenSearch support shipped through a custom Docker image
built from [`awslabs/ai-on-eks`](https://github.com/awslabs/ai-on-eks) via `./deploy.sh build`. On
v2.0, OpenSearch is a built-in knowledge backend selected through workflow YAML
(`backend: opensearch`). You no longer need to maintain a custom image build pipeline.
```

## Architecture

```{mermaid}
flowchart LR
    user[User / UI] -->|HTTPS| backend[aiq-agent pod<br/>service account: aiq-backend]
    backend -->|submit ingest| dask_sched[Dask scheduler]
    dask_sched --> dask_worker[Dask worker<br/>same service account]
    backend -->|SigV4 retrieval| aoss[(Amazon OpenSearch<br/>Serverless collection)]
    dask_worker -->|SigV4 ingest| aoss
    pod_identity[EKS Pod Identity<br/>association] -.maps SA to.-> iam[IAM role<br/>aoss:APIAccessAll]
    iam -.assumed by.-> backend
    iam -.assumed by.-> dask_worker
    aoss_dap[AOSS data access policy] -.grants index ops.-> iam
```

The backend pod and every Dask worker assume the same IAM role through the EKS Pod Identity
association on the `aiq-backend` service account. Each Dask worker constructs its own OpenSearch
client, so SigV4 signing happens in the worker's process — no signer state is serialized across
the cluster.

## Prerequisites

| Item | Version / detail |
|------|------------------|
| AWS account | with permissions to create AOSS collections, IAM roles, and EKS Pod Identity associations |
| AWS CLI | v2.15+ (Pod Identity associations require recent AWS CLI) |
| `kubectl` | v1.29+ |
| `helm` | v3.14+ |
| EKS cluster | v1.29+ with the EKS Pod Identity Agent add-on installed |
| Region | the same region for the EKS cluster and the AOSS collection |
| `nvcr.io` access | NGC API key for pulling `nvcr.io/nvidia/blueprint/aiq-agent` |

Install the EKS Pod Identity Agent add-on once per cluster:

```bash
aws eks create-addon \
  --cluster-name <cluster-name> \
  --addon-name eks-pod-identity-agent
```

Confirm it is `ACTIVE` before continuing:

```bash
aws eks describe-addon --cluster-name <cluster-name> --addon-name eks-pod-identity-agent \
  --query 'addon.status' --output text
```

Expected: `ACTIVE`.

## Workflow Config

Use `configs/config_web_opensearch.yml`:

```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: opensearch
    collection_name: ${COLLECTION_NAME:-test_collection}
    opensearch_url: ${OPENSEARCH_URL}
    opensearch_auth_type: sigv4
    opensearch_aws_region: ${AWS_REGION}
    opensearch_aws_service: aoss
    opensearch_index_prefix: ${OPENSEARCH_INDEX_PREFIX:-aiq}
    opensearch_ingestion_mode: ${OPENSEARCH_INGESTION_MODE:-auto}
    opensearch_dask_file_transfer: ${OPENSEARCH_DASK_FILE_TRANSFER:-bytes}
```

Session collection names such as `s_<uuid>` map to physical indexes like `aiq-s_<uuid>` inside the same Serverless
collection endpoint. The backend stores collection metadata in mapping `_meta` and the TTL cleanup thread deletes
expired session indexes.

## EKS Pod Identity

For EKS deployments, use Pod Identity to provide AWS credentials to the backend pod and any Dask worker process. With the
default Helm release names, the namespace is `ns-aiq` and the backend service account is `aiq-backend`.

Create the Pod Identity association outside the chart:

```bash
aws eks create-pod-identity-association \
  --cluster-name <cluster-name> \
  --namespace ns-aiq \
  --service-account aiq-backend \
  --role-arn arn:aws:iam::<account-id>:role/<aiq-opensearch-role>
```

The IAM role must allow OpenSearch Serverless API access to the target collection. The collection must also have a data
access policy granting index permissions to the same role. For dynamic AI-Q indexes, use an index resource pattern such
as `index/<collection-name>/aiq*`.

## Helm Values

Use the example values file as a starting point:

```bash
helm upgrade --install aiq deploy/helm/deployment-k8s \
  -n ns-aiq --create-namespace \
  -f deploy/helm/examples/aws-opensearch-serverless-values.yaml
```

Override the backend image when testing unreleased code:

```yaml
aiq:
  apps:
    backend:
      image:
        repository: <registry>/<aiq-agent-image>
        tag: <tag>
```

## Local Live Test

For SSO credentials, clear stale environment credentials before running the test. Environment credentials take
precedence over `AWS_PROFILE`.

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_CREDENTIAL_EXPIRATION
aws sso login --profile cs-admin

AIQ_OPENSEARCH_SERVERLESS_LIVE_TESTS=1 \
OPENSEARCH_URL=https://abc123.us-west-2.aoss.amazonaws.com \
AWS_REGION=us-west-2 \
AWS_PROFILE=cs-admin \
uv run python -m pytest tests/knowledge_layer_tests/test_opensearch_serverless_live.py -rs -vv
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `403` from AOSS | Missing IAM or data access policy | Grant `aoss:APIAccessAll` and AOSS data access permissions for the index pattern |
| `Credentials were refreshed, but the refreshed credentials are still expired` | Stale exported AWS session credentials override SSO | Unset the `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and `AWS_CREDENTIAL_EXPIRATION` variables |
| Empty results immediately after ingest | AOSS search visibility delay | Retry retrieval; live tests wait for document visibility |
| Mapping dimension error | Embedding model dimension does not match index mapping | Set `OPENSEARCH_EMBEDDING_DIM` before creating the index |
