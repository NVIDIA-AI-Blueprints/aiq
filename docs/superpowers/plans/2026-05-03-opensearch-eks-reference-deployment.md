# OpenSearch EKS Reference Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OpenSearch / Amazon OpenSearch Serverless reference deployment on EKS with Pod Identity self-contained inside this repo, so an AWS customer can stand up AIQ 2.0 end-to-end without forking images or hunting through external docs.

**Architecture:** Pure docs + example values + verification commands. No application code in this plan (gaps/risks are deferred to a follow-up plan). The existing OpenSearch adapter, registration, helm chart, and helm example values stay as they are. We deepen `docs/source/deployment/aws-opensearch-serverless.md` and `deploy/helm/examples/aws-opensearch-serverless-values.yaml` so the doc walks a customer from "have an AWS account" to "AIQ pod is querying AOSS via SigV4 from Dask workers using EKS Pod Identity."

**Tech Stack:** MyST/Markdown (Sphinx with `myst_parser`, `sphinxmermaid`), YAML (Helm values, NAT workflow config), AWS CLI (`aoss`, `iam`, `eks`), `kubectl`, `helm`.

**Spec mapping (PR ask #6, awslabs publishing removed):**
- "A reference YAML config" → `configs/config_web_opensearch.yml` (already exists; verified in Task 11).
- "EKS deployment docs using Pod Identity" → `docs/source/deployment/aws-opensearch-serverless.md` (today: 99 lines, thin) is expanded by Tasks 1–10.

**Working file inventory (read these before starting):**
- `docs/source/deployment/aws-opensearch-serverless.md` — primary doc, expanded throughout.
- `deploy/helm/examples/aws-opensearch-serverless-values.yaml` — example values, gets `imagePullSecrets` and embedding wiring.
- `deploy/helm/README.md` — already cross-links the example file (no further changes here).
- `docs/source/deployment/index.md` — already lists the new doc on line 30 (no further changes here).
- `configs/config_web_opensearch.yml` — workflow config, already env-substitution-driven (no further changes here).
- `sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md` — gets one cross-link added in Task 11.

---

## Task 1: Add v1.0 → v2.0 migration callout at the top of the AOSS doc

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert after the H1 on line 6)

**Why:** The PR is framed as closing the v1.0/v2.0 gap. AWS readers landing on this page need to see in the first 10 seconds that they no longer need the `./deploy.sh build` custom-image step from the v1.0 reference. Without this, customers will assume the v1.0 fork pattern is still required.

- [ ] **Step 1: Insert the migration note**

Open `docs/source/deployment/aws-opensearch-serverless.md`. After the existing line 8 paragraph (the one starting "AI-Q can use the built-in OpenSearch knowledge backend…"), insert:

```markdown
:::{note} Migrating from AI-Q v1.0
On v1.0, OpenSearch support shipped through a custom Docker image built from
[`awslabs/ai-on-eks`](https://github.com/awslabs/ai-on-eks) via `./deploy.sh build`. On v2.0,
OpenSearch is a built-in knowledge backend selected through workflow YAML
(`backend: opensearch`). You no longer need to fork or rebuild the NVIDIA base images.
:::
```

The `:::{note}` syntax is a MyST admonition; this repo's `conf.py` enables `colon_fence` so it renders as a callout box in Sphinx output.

- [ ] **Step 2: Render the page locally and confirm the callout shows**

Run from the repo root:

```bash
cd docs && make html
```

Expected: build completes with no warnings about the new file. Open `docs/_build/html/source/deployment/aws-opensearch-serverless.html` in a browser and confirm the green/blue note box appears under the H1.

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): add v1.0 to v2.0 migration callout to AOSS guide"
```

---

## Task 2: Add an architecture diagram to the AOSS doc

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert a new `## Architecture` section above `## Workflow Config`)

**Why:** The non-obvious part of this design is that Dask workers create their own OpenSearch client so SigV4 credentials resolve in the worker's process (Pod Identity, SSO, env profiles). A diagram makes this "aha" visible. Mermaid is already enabled via `sphinxmermaid` in `docs/source/conf.py`.

- [ ] **Step 1: Insert the architecture section**

Above the `## Workflow Config` heading, insert:

```markdown
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
```

(The triple-backtick `{mermaid}` fence is the MyST/Sphinx mermaid directive.)

- [ ] **Step 2: Render and confirm the diagram appears**

Run:

```bash
cd docs && make html
```

Expected: build completes, diagram renders as SVG in the HTML output.

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): add architecture diagram showing SigV4 in Dask workers"
```

---

## Task 3: Add a Prerequisites section

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert `## Prerequisites` immediately after `## Architecture`)

**Why:** The current doc assumes you already have an EKS cluster, AOSS collection, IAM role, and Pod Identity association. New readers fall off here. A prerequisites section sets expectations and lists exact tool versions.

- [ ] **Step 1: Insert prerequisites**

```markdown
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
```

- [ ] **Step 2: Render and confirm**

```bash
cd docs && make html
```

Expected: no Sphinx warnings, the new section renders as a table plus two code blocks.

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): list EKS and tooling prerequisites for AOSS deployment"
```

---

## Task 4: Add an end-to-end AOSS collection creation walkthrough

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert `## Create the OpenSearch Serverless collection` after `## Prerequisites`)

**Why:** AOSS requires an encryption policy and a network policy *before* the collection can be created. This trips up first-time AOSS users. Today the doc only shows the Pod Identity command and skips collection creation entirely.

- [ ] **Step 1: Insert the collection creation walkthrough**

```markdown
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
```

- [ ] **Step 2: Render and confirm three numbered subsections appear**

```bash
cd docs && make html
```

Expected: H3 entries 1, 2, 3 in the right-side TOC.

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): walk through AOSS encryption, network, and collection creation"
```

---

## Task 5: Document the IAM role and trust policy for Pod Identity

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert `## IAM role for the AIQ pod` after the collection creation section)

**Why:** Pod Identity uses a trust policy that names `pods.eks.amazonaws.com`, which is different from IRSA's OIDC trust policy. Customers familiar with IRSA will write the wrong trust policy. The doc must show the exact trust policy.

- [ ] **Step 1: Insert the IAM role section**

```markdown
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
```

- [ ] **Step 2: Render and verify both JSON code fences highlight as JSON**

```bash
cd docs && make html
```

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): document Pod Identity trust policy and AOSS IAM permissions"
```

---

## Task 6: Document the AOSS data access policy and Pod Identity association

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` — replace the existing thin `## EKS Pod Identity` section (currently lines ~36–53 of the file) with a deeper version that covers the AOSS data access policy and the association command.

**Why:** AOSS has a second authorization layer (data access policies) on top of IAM. Customers stop at IAM, hit a 403, and don't know that the *index resource pattern* is the missing piece. The current doc mentions this in passing — the new section makes it explicit and shows the JSON.

- [ ] **Step 1: Replace the existing `## EKS Pod Identity` section**

Delete the current `## EKS Pod Identity` block and replace it with:

```markdown
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
```

- [ ] **Step 2: Render and confirm both new H2 sections appear in the page TOC**

```bash
cd docs && make html
```

Expected: side TOC shows "Grant the role access to AOSS" and "Associate the role with the AIQ service account".

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): expand Pod Identity section with AOSS data access policy"
```

---

## Task 7: Add `imagePullSecrets` to the example Helm values and document the NGC secret

**Files:**
- Modify: `deploy/helm/examples/aws-opensearch-serverless-values.yaml`
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (extend the `## Helm Values` section)

**Why:** The example values point at `nvcr.io/nvidia/blueprint/aiq-agent` but customers have no way to pull from `nvcr.io` without an `imagePullSecret`. This is the most common first-failure mode. Fix it in the example, document the secret creation.

- [ ] **Step 1: Add `imagePullSecrets` to the example values**

Edit `deploy/helm/examples/aws-opensearch-serverless-values.yaml` so the `backend` block reads:

```yaml
aiq:
  apps:
    backend:
      image:
        repository: nvcr.io/nvidia/blueprint/aiq-agent
        tag: "2.0.0"
        pullPolicy: IfNotPresent
      imagePullSecrets:
        - name: ngc-image-pull-secret
      env:
        CONFIG_FILE: configs/config_web_opensearch.yml
        COLLECTION_NAME: default_collection
        OPENSEARCH_URL: https://abc123.us-west-2.aoss.amazonaws.com
        OPENSEARCH_AUTH_TYPE: sigv4
        OPENSEARCH_AWS_SERVICE: aoss
        OPENSEARCH_INDEX_PREFIX: aiq
        AWS_REGION: us-west-2
        OPENSEARCH_INGESTION_MODE: auto
        OPENSEARCH_DASK_FILE_TRANSFER: bytes
        DASK_NWORKERS: "1"
        DASK_NTHREADS: "4"
```

Verify the file parses:

```bash
python -c "import yaml; yaml.safe_load(open('deploy/helm/examples/aws-opensearch-serverless-values.yaml'))"
```

Expected: no output (valid YAML).

- [ ] **Step 2: Add a `### Pull secret for nvcr.io` subsection under `## Helm Values` in the AOSS doc**

Insert before the existing `helm upgrade --install` block:

```markdown
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
```

- [ ] **Step 3: Render and confirm both files**

```bash
cd docs && make html
```

Expected: Sphinx build clean. Open the AOSS page and confirm the new `### Pull secret for nvcr.io` subsection appears under `## Helm Values`.

- [ ] **Step 4: Commit**

```bash
git add deploy/helm/examples/aws-opensearch-serverless-values.yaml docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): add nvcr.io pull secret to example values and AOSS guide"
```

---

## Task 8: Document the embedding endpoint configuration

**Files:**
- Modify: `deploy/helm/examples/aws-opensearch-serverless-values.yaml` (add `NVIDIA_API_KEY` wiring through a Kubernetes secret)
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (add `### Embedding endpoint` under `## Helm Values`)

**Why:** The OpenSearch ingestor needs an embedding endpoint. By default it calls `https://integrate.api.nvidia.com/v1` and requires `NVIDIA_API_KEY`. The example values do not show how to provide that key, so customers will silently 401. Document both the hosted-API path and the NIM-on-EKS override path.

- [ ] **Step 1: Add the secret env wiring to the example values**

Add to the `backend.env` block in `deploy/helm/examples/aws-opensearch-serverless-values.yaml`:

```yaml
      envFromSecret:
        - name: nvidia-api-key
          key: NVIDIA_API_KEY
          envVar: NVIDIA_API_KEY
```

If the chart's existing schema for secret env wiring uses a different key (verify against
`deploy/helm/deployment-k8s/values.yaml` and the `_helpers.tpl` template before committing —
this repo's chart may use `extraEnvVarsSecret` or similar), update the example to match.
The intent: NVIDIA_API_KEY is sourced from a Kubernetes secret, not hard-coded into values.

Verify the file still parses:

```bash
python -c "import yaml; yaml.safe_load(open('deploy/helm/examples/aws-opensearch-serverless-values.yaml'))"
```

- [ ] **Step 2: Add the embedding endpoint subsection to the AOSS doc**

Insert under `## Helm Values`, after the pull secret subsection:

```markdown
### Embedding endpoint

The OpenSearch ingestor calls an OpenAI-compatible embeddings endpoint to vectorize chunks
before indexing. Two options:

**Option A: NVIDIA hosted API (default).** The ingestor calls
`https://integrate.api.nvidia.com/v1` and reads `NVIDIA_API_KEY` from the pod environment.
Create the secret once, then the example values mount it:

```bash
kubectl -n ns-aiq create secret generic nvidia-api-key \
  --from-literal=NVIDIA_API_KEY=<your-nvidia-api-key>
```

**Option B: Self-hosted NIM on the same cluster.** Override `AIQ_EMBED_BASE_URL` to your
NIM service and leave `NVIDIA_API_KEY` empty. Add to `backend.env`:

```yaml
        AIQ_EMBED_BASE_URL: http://nim-embedqa.ns-nim.svc.cluster.local:8000/v1
        AIQ_EMBED_MODEL: nvidia/llama-nemotron-embed-vl-1b-v2
```

The embedding model dimension must match `OPENSEARCH_EMBEDDING_DIM` in the workflow config
(default `2048` for `nvidia/llama-nemotron-embed-vl-1b-v2`). Mismatched dimensions surface
as `mapper_parsing_exception` on the first ingest.
```

- [ ] **Step 3: Render and verify**

```bash
cd docs && make html
```

- [ ] **Step 4: Commit**

```bash
git add deploy/helm/examples/aws-opensearch-serverless-values.yaml docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): document hosted-API and NIM-on-EKS embedding setups"
```

---

## Task 9: Add a verification / smoke test section

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert `## Verify the deployment` after the `## Helm Values` section, before `## Local Live Test`)

**Why:** After install there's no guidance for "did it actually work". A smoke test (port-forward, health check, upload a doc, search) catches the common failures (Pod Identity not associated, AOSS data policy missing, dimension mismatch) inside ten minutes.

- [ ] **Step 1: Insert the verification section**

```markdown
## Verify the deployment

### 1. Pod is running and Pod Identity is attached

```bash
kubectl -n ns-aiq get pods -l app.kubernetes.io/name=aiq-agent
kubectl -n ns-aiq describe pod -l app.kubernetes.io/name=aiq-agent | grep -A2 'AWS_CONTAINER_CREDENTIALS'
```

Expected: pod is `Running`, the describe output shows
`AWS_CONTAINER_CREDENTIALS_FULL_URI` injected by the EKS Pod Identity Agent. If that variable
is missing, the Pod Identity association is not in effect — re-check the cluster, namespace,
and service-account triple in Task 6.

### 2. Backend health check

```bash
kubectl -n ns-aiq port-forward svc/aiq-agent 8000:8000 &
curl -sf http://localhost:8000/health
```

Expected: `{"status":"ok"}` (or equivalent — match the health route exposed by the deployed
`aiq_api` front end).

### 3. Upload a document

```bash
curl -sf -X POST http://localhost:8000/v1/collections \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke","description":"smoke test"}'

curl -sf -X POST http://localhost:8000/v1/collections/smoke/documents \
  -F 'files=@README.md'
```

Expected: a `job_id` is returned. Poll `GET /v1/documents/{job_id}/status` until `status` is
`SUCCESS`. If it stalls in `INGESTING`, check the Dask worker logs for SigV4 errors:

```bash
kubectl -n ns-aiq logs -l app.kubernetes.io/name=aiq-agent --tail=200 | grep -i opensearch
```

### 4. Confirm the index appears in AOSS

```bash
aws opensearchserverless list-collections --region "$REGION"
```

```bash
curl -sf "http://localhost:8000/v1/collections" | jq
```

Expected: `aiq-smoke` index visible in the AOSS console under the collection's index browser,
and the `smoke` collection listed by the AIQ API.

### 5. Run a knowledge query

```bash
curl -sf -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"what is in the smoke document"}]}'
```

Expected: response includes content from `README.md` with citations.
```

- [ ] **Step 2: Render and verify the H3 anchors render**

```bash
cd docs && make html
```

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): add end-to-end verification and smoke test for AOSS install"
```

---

## Task 10: Add a teardown section

**Files:**
- Modify: `docs/source/deployment/aws-opensearch-serverless.md` (insert `## Cleanup` after `## Troubleshooting`)

**Why:** AOSS collections cost money. Customers running this for a demo need a one-shot teardown so they don't leave a paid collection running. Also helps reviewers reproduce the demo without leaving artifacts.

- [ ] **Step 1: Insert cleanup section**

```markdown
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
```

- [ ] **Step 2: Render**

```bash
cd docs && make html
```

- [ ] **Step 3: Commit**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): add teardown commands for AOSS reference deployment"
```

---

## Task 11: Cross-link from main READMEs and validate the reference YAML

**Files:**
- Modify: `sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md` (add a deployment cross-link near the OpenSearch SigV4 example)
- Read-only verification: `configs/config_web_opensearch.yml` (no changes; just confirm it matches the doc)

**Why:** The AOSS deployment doc is discoverable from `docs/source/deployment/index.md` already, but the knowledge layer setup guide — where customers land first when learning about backends — does not link out to the EKS-specific guide. Add the cross-link.

- [ ] **Step 1: Add the cross-link in `KNOWLEDGE-LAYER-SETUP.md`**

Find the AOSS example block (around line 220 of `sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md`, the YAML showing `opensearch_aws_service: aoss`). Immediately after that YAML block, add:

```markdown
> **Deploying on EKS?** See the
> [Amazon OpenSearch Serverless deployment guide](../../docs/source/deployment/aws-opensearch-serverless.md)
> for the end-to-end EKS Pod Identity setup, AOSS data access policy, Helm values, and
> verification commands.
```

- [ ] **Step 2: Validate the reference YAML still loads cleanly**

The reference YAML config is part of ask #6. Confirm it parses and references the existing
backend identifier:

```bash
python -c "
import yaml
cfg = yaml.safe_load(open('configs/config_web_opensearch.yml'))
ks = cfg['functions']['knowledge_search']
assert ks['_type'] == 'knowledge_retrieval'
assert ks['backend'] == 'opensearch'
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add sources/knowledge_layer/KNOWLEDGE-LAYER-SETUP.md
git commit -m "docs(knowledge): link OpenSearch backend setup to EKS deployment guide"
```

---

## Task 12: Final docs build with `-W` (warnings as errors)

**Files:** none (verification only)

**Why:** Catches broken cross-references introduced by Task 11's relative link, mermaid syntax errors, MyST admonition typos, and any other Sphinx warnings. This is the equivalent of "run the test suite green" for a docs PR.

- [ ] **Step 1: Run a strict build**

```bash
cd docs
make clean
SPHINXOPTS="-W --keep-going -n" make html
```

Expected: build exits 0 with no warnings. The `-W` turns warnings into errors; `-n` enables nitpicky mode for cross-references; `--keep-going` reports every warning rather than stopping at the first.

If warnings appear, fix them in place (typically: bad relative paths, missing TOC entries, malformed mermaid). Re-run until clean.

- [ ] **Step 2: Open the rendered AOSS page and skim end-to-end**

Open `docs/_build/html/source/deployment/aws-opensearch-serverless.html` in a browser. Walk
through it in order. Confirm: migration callout, mermaid diagram, prerequisites, AOSS
collection creation, IAM role, AOSS data access policy, Pod Identity association, helm pull
secret, embedding setup, verify steps, troubleshooting, cleanup. The reading flow should be a
straight line from "I have an AWS account" to "I have a working AIQ + AOSS deployment."

- [ ] **Step 3: Commit any fixes from Step 1 (only if any)**

```bash
git add docs/source/deployment/aws-opensearch-serverless.md
git commit -m "docs(opensearch): resolve sphinx -W warnings in AOSS deployment guide"
```

---

## Out of scope (handled in the follow-up plan)

The follow-up "gaps/risks" plan covers:
1. `_embed_texts` empty-key fallback in `sources/knowledge_layer/src/opensearch/adapter.py:508`.
2. `OpenSearchAwsService` literal coercion edge case in `sources/knowledge_layer/src/register.py:42`.
3. Multimodal extraction parity (or explicit "text-only" callout) for the OpenSearch backend.
4. Committing this entire OpenSearch branch — currently every file is unstaged or untracked, so step zero before any of the above is a clean PR against `develop`.
