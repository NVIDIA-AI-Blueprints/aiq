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

## Create the OpenSearch Serverless collection

AOSS requires an encryption policy and a network policy before the collection can be created.
Replace `<collection-name>` and `<region>` throughout. The examples below use AWS-owned KMS keys
and a public network policy; harden these for production.

### 1. Encryption policy

```bash
COLLECTION=<collection-name>
REGION=<region>

aws opensearchserverless create-security-policy \
  --region "$REGION" \
  --name "${COLLECTION}-enc" \
  --type encryption \
  --policy "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION}\"]}],\"AWSOwnedKey\":true}"
```

### 2. Network policy

```bash
aws opensearchserverless create-security-policy \
  --region "$REGION" \
  --name "${COLLECTION}-net" \
  --type network \
  --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION}\"]},{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/${COLLECTION}\"]}],\"AllowFromPublic\":true}]"
```

For private VPC access, replace `AllowFromPublic` with `SourceVPCEs`. See the
[AOSS network policy docs](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-network.html).

### 3. Create the collection

```bash
aws opensearchserverless create-collection \
  --region "$REGION" \
  --name "$COLLECTION" \
  --type VECTORSEARCH
```

Wait until the collection is `ACTIVE` and capture the data endpoint:

```bash
aws opensearchserverless batch-get-collection \
  --region "$REGION" --names "$COLLECTION" \
  --query 'collectionDetails[0].[status,collectionEndpoint]' --output text
```

Expected output: `ACTIVE   https://abc123.<region>.aoss.amazonaws.com`. Save the endpoint — it
is the `OPENSEARCH_URL` value used in Helm values.

## IAM role for the AIQ pod

Pod Identity assumes an IAM role through `pods.eks.amazonaws.com`. The trust policy for this role
must allow `sts:AssumeRole` and `sts:TagSession` for that principal.

### 1. Trust policy

Save as `aiq-trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "pods.eks.amazonaws.com" },
      "Action": ["sts:AssumeRole", "sts:TagSession"]
    }
  ]
}
```

### 2. Permissions policy

The role needs `aoss:APIAccessAll` on the collection, plus the AOSS dashboard endpoint if you
want to inspect indexes from the AWS console. Save as `aiq-permissions-policy.json` and substitute
your account ID and collection name:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "aoss:APIAccessAll",
      "Resource": "arn:aws:aoss:<region>:<account-id>:collection/<collection-id>"
    }
  ]
}
```

The `<collection-id>` is the suffix returned by `batch-get-collection` under `id` (a 26-character
identifier), not the human-readable name.

### 3. Create the role

```bash
aws iam create-role \
  --role-name aiq-opensearch-role \
  --assume-role-policy-document file://aiq-trust-policy.json

aws iam put-role-policy \
  --role-name aiq-opensearch-role \
  --policy-name aiq-opensearch-access \
  --policy-document file://aiq-permissions-policy.json
```

Capture the role ARN — it goes into the Pod Identity association in Task 6.

```bash
aws iam get-role --role-name aiq-opensearch-role --query 'Role.Arn' --output text
```

## Grant the role access to AOSS

AOSS authorizes data plane operations (index create, document write, search) through a
*data access policy* that is separate from IAM. The policy lists IAM principals and the
collections/indexes they can act on.

Save as `aiq-data-access-policy.json`. Substitute your role ARN and AIQ index prefix
(`aiq` matches the default `OPENSEARCH_INDEX_PREFIX`):

```json
[
  {
    "Rules": [
      {
        "ResourceType": "collection",
        "Resource": ["collection/<collection-name>"],
        "Permission": ["aoss:DescribeCollectionItems"]
      },
      {
        "ResourceType": "index",
        "Resource": ["index/<collection-name>/aiq*"],
        "Permission": [
          "aoss:CreateIndex",
          "aoss:DeleteIndex",
          "aoss:UpdateIndex",
          "aoss:DescribeIndex",
          "aoss:ReadDocument",
          "aoss:WriteDocument"
        ]
      }
    ],
    "Principal": ["arn:aws:iam::<account-id>:role/aiq-opensearch-role"],
    "Description": "AIQ backend access to AOSS indexes"
  }
]
```

```bash
aws opensearchserverless create-access-policy \
  --region "$REGION" \
  --name "${COLLECTION}-aiq" \
  --type data \
  --policy file://aiq-data-access-policy.json
```

The index resource pattern `index/<collection>/aiq*` covers every AIQ session collection, since
the OpenSearch backend creates indexes named `aiq-<collection>` (or `aiq-s_<uuid>` for session
collections).

## Associate the role with the AIQ service account

EKS Pod Identity binds an IAM role to a Kubernetes service account. With the default Helm
release names, the namespace is `ns-aiq` and the backend service account is `aiq-backend`.

```bash
aws eks create-pod-identity-association \
  --cluster-name <cluster-name> \
  --namespace ns-aiq \
  --service-account aiq-backend \
  --role-arn arn:aws:iam::<account-id>:role/aiq-opensearch-role
```

The same service account is used by the embedded Dask scheduler and worker, so SigV4
credentials are available throughout the ingestion pipeline. No service-account annotation is
required — Pod Identity does not use OIDC trust like IRSA.

## Workflow Config

Use `configs/config_web_opensearch.yml`:

```{note}
**Text-only ingestion.** The OpenSearch backend extracts plain text from PDFs, DOCX, and PPTX. It does
not currently support table/image/chart extraction (those flags are LlamaIndex-only). For multimodal,
use the LlamaIndex backend or Foundational RAG.
```

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

## Helm Values

Use the example values file as a starting point:

### Pull secret for `nvcr.io`

The example values reference `nvcr.io/nvidia/blueprint/aiq-agent`. Create an NGC API key at
[`ngc.nvidia.com`](https://ngc.nvidia.com), then create the pull secret in the release namespace:

```bash
kubectl create namespace ns-aiq --dry-run=client -o yaml | kubectl apply -f -

kubectl -n ns-aiq create secret docker-registry ngc-image-pull-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<your-ngc-api-key>
```

The secret name `ngc-image-pull-secret` matches the
[`deploy/helm/examples/aws-opensearch-serverless-values.yaml`](../../../deploy/helm/examples/aws-opensearch-serverless-values.yaml)
`imagePullSecrets` entry. Change both if you use a different name.

### Embedding endpoint

The OpenSearch ingestor calls an OpenAI-compatible embeddings endpoint to vectorize chunks
before indexing. Two options:

**Option A: NVIDIA hosted API (default).** The ingestor calls
`https://integrate.api.nvidia.com/v1` and reads `NVIDIA_API_KEY` from the pod environment.
Create the shared credentials secret once and the example values' `secretEnv` block injects
`NVIDIA_API_KEY` into the backend container:

```bash
kubectl -n ns-aiq create secret generic aiq-credentials \
  --from-literal=NVIDIA_API_KEY=<your-nvidia-api-key>
```

The chart's `secretEnv` pattern maps env-var names to keys in this shared secret. Add other
keys (database credentials, etc.) to the same secret if your release needs them.

**Option B: Self-hosted NIM on the same cluster.** Override `AIQ_EMBED_BASE_URL` to point at
your in-cluster NIM service and leave `NVIDIA_API_KEY` empty. Add to `backend.env` in your
values:

```yaml
        AIQ_EMBED_BASE_URL: http://nim-embedqa.ns-nim.svc.cluster.local:8000/v1
        AIQ_EMBED_MODEL: nvidia/llama-nemotron-embed-vl-1b-v2
```

The embedding model dimension must match `OPENSEARCH_EMBEDDING_DIM` in the workflow config
(default `2048` for `nvidia/llama-nemotron-embed-vl-1b-v2`). Mismatched dimensions surface
as `mapper_parsing_exception` on the first ingest.

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

## Verify the deployment

### 1. Pod is running and Pod Identity is attached

```bash
kubectl -n ns-aiq get pods -l app=aiq-backend
kubectl -n ns-aiq describe pod -l app=aiq-backend | grep -A2 'AWS_CONTAINER_CREDENTIALS'
```

Expected: pod is `Running`, the describe output shows
`AWS_CONTAINER_CREDENTIALS_FULL_URI` injected by the EKS Pod Identity Agent. If that variable
is missing, the Pod Identity association is not in effect — re-check the cluster, namespace,
and service-account triple in the previous section.

### 2. Backend health check

```bash
kubectl -n ns-aiq port-forward svc/aiq-backend 8000:8000 &
curl -sf http://localhost:8000/health
```

Expected: `{"status":"healthy"}` (the `aiq_api` front end exposes a JSON health route at `/health`).

### 3. Upload a document

```bash
curl -sf -X POST http://localhost:8000/v1/collections \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke","description":"smoke test"}'

curl -sf -X POST http://localhost:8000/v1/collections/smoke/documents \
  -F 'files=@README.md'
```

Expected: a `job_id` is returned. Poll `GET /v1/documents/{job_id}/status` until `status` is
`completed`. If it stalls in `processing`, check the backend pod logs for SigV4/credential errors.
The Dask scheduler and workers run embedded in the backend pod, so ingestion errors surface there.
Read the raw tail rather than filtering it, so an auth failure that doesn't mention "opensearch" is not hidden:

```bash
kubectl -n ns-aiq logs -l app=aiq-backend --tail=200
```

### 4. Confirm the index appears in AOSS

```bash
aws opensearchserverless list-collections --region "$REGION"
```

```bash
curl -sf "http://localhost:8000/v1/collections" | jq
```

Expected: an `aiq-smoke-<hash>` index visible in the AOSS console under the collection's index browser
(the physical index name appends a stable disambiguator to the logical `smoke` collection),
and the `smoke` collection listed by the AIQ API.

```{note}
**AOSS visibility delay.** AOSS is eventually consistent for search after writes. A `_count` immediately
after a successful upload may report `0` for ~5–30 seconds before catching up. If the AIQ status says
`completed` but the AOSS console index browser shows zero docs, wait 30s and refresh — the index will
populate. This is also why the live-test suite includes a polling visibility wait.
```

### 5. Run a knowledge query

```bash
curl -sf -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'conversation-id: smoke' \
  -d '{"messages":[{"role":"user","content":"what is in the smoke document"}]}'
```

The `conversation-id` header selects the collection to search (the backend maps `conversation-id`
to the collection name), so it must match the `smoke` collection created above.

Expected: response includes content from `README.md` with citations.

## Local Live Test

For SSO credentials, clear stale environment credentials before running the test. Environment credentials take
precedence over `AWS_PROFILE`.

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_CREDENTIAL_EXPIRATION
aws sso login --profile cs-admin
aws sts get-caller-identity --profile cs-admin

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
| Dask worker stdout is empty during local testing | `DASK_DISTRIBUTED__LOGGING__DISTRIBUTED=warning` (default in `deploy/.env`) silences worker logs. Ingestion still succeeds — verify by counting docs in AOSS, not by tailing the worker. | Override locally with `DASK_DISTRIBUTED__LOGGING__DISTRIBUTED=info` if you need worker logs during development. |

## Cleanup

```bash
helm uninstall aiq -n ns-aiq
kubectl delete namespace ns-aiq

aws eks delete-pod-identity-association \
  --cluster-name <cluster-name> \
  --association-id <association-id>

aws iam delete-role-policy --role-name aiq-opensearch-role --policy-name aiq-opensearch-access
aws iam delete-role --role-name aiq-opensearch-role

aws opensearchserverless delete-access-policy --type data --name "${COLLECTION}-aiq"
aws opensearchserverless delete-collection --id <collection-id>
aws opensearchserverless delete-security-policy --type network --name "${COLLECTION}-net"
aws opensearchserverless delete-security-policy --type encryption --name "${COLLECTION}-enc"
```

Get the Pod Identity `<association-id>` with:

```bash
aws eks list-pod-identity-associations \
  --cluster-name <cluster-name> --namespace ns-aiq \
  --query 'associations[?serviceAccount==`aiq-backend`].associationId' --output text
```

Get the AOSS `<collection-id>` with:

```bash
aws opensearchserverless batch-get-collection --names "$COLLECTION" \
  --query 'collectionDetails[0].id' --output text
```
