<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Kubernetes (Helm)

Deploy the AI-Q blueprint to a Kubernetes cluster using the Helm charts included in the repository.

## Prerequisites

- Kubernetes cluster (EKS, GKE, AKS, or a local cluster such as Kind or Minikube).
- `kubectl` configured with cluster access.
- `helm` v3.x installed.
- API keys for the models and tools you plan to use (refer to [Installation -- API Key Setup](../get-started/installation.md#api-key-setup)).

## Chart Structure

The Helm deployment lives under `deploy/helm/`:

```
deploy/helm/
├── deployment-k8s/
│   ├── Chart.yaml        # Chart definition (depends on helm-charts-k8s/aiq)
│   ├── values.yaml       # Deployment values
│   └── README.md
└── helm-charts-k8s/
    └── aiq/              # Base application Helm chart
```

`deployment-k8s/` references `helm-charts-k8s/aiq` as a local file dependency. Both directories must be present at the same level.

## Setup

### 1. Create a namespace

```bash
kubectl create namespace ns-aiq
```

### 2. Create the credentials secret

The deployment reads API keys and database credentials from a Kubernetes Secret named `aiq-credentials`:

```bash
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="$NVIDIA_API_KEY" \
  --from-literal=TAVILY_API_KEY="$TAVILY_API_KEY" \
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="$DB_USER_PASSWORD"
```

### 3. Create an image pull secret (NGC registry)

If you are pulling pre-built images from the NGC container registry, create a Docker registry secret:

```bash
kubectl create secret docker-registry ngc-secret -n ns-aiq \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password="<YOUR_NGC_API_KEY>"
```

## Deploy

### Using pre-built NGC images

```bash
cd deploy/helm

helm dependency update deployment-k8s/

helm install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.imagePullSecrets[0].name=ngc-secret \
  --set aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret \
  --set aiq.apps.backend.image.repository=nvcr.io/nvidia/blueprint/aiq-agent \
  --set aiq.apps.frontend.image.repository=nvcr.io/nvidia/blueprint/aiq-frontend
```

### Using locally built images

If you built images locally (see [Docker Build System](./docker-build.md)), set the image references to your local tags:

```bash
cd deploy/helm

helm dependency update deployment-k8s/

helm install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.image.repository=aiq-agent \
  --set aiq.apps.backend.image.tag=dev \
  --set aiq.apps.backend.image.pullPolicy=IfNotPresent \
  --set aiq.apps.frontend.image.repository=aiq-frontend \
  --set aiq.apps.frontend.image.tag=dev \
  --set aiq.apps.frontend.image.pullPolicy=IfNotPresent
```

For Kind clusters, load local images first with `kind load docker-image`. Refer to the "Getting Started with Minimal K8s (Kind)" section in `deploy/helm/deployment-k8s/README.md`.

### Verify

```bash
kubectl get pods -n ns-aiq
```

Expected output:

```
NAME                            READY   STATUS    RESTARTS   AGE
aiq-backend-xxx                 1/1     Running   0          30s
aiq-frontend-xxx                1/1     Running   0          30s
aiq-postgres-xxx                1/1     Running   0          30s
```

### Health check

Once all pods are running, verify the backend is responding:

```bash
kubectl port-forward -n ns-aiq svc/aiq-backend 8000:8000 &
curl http://localhost:8000/health
```

The backend API docs are available at `http://localhost:8000/docs` while the port-forward is active.

### Access the application

```bash
# Frontend UI
kubectl port-forward -n ns-aiq svc/aiq-frontend 3000:3000

# Backend API
kubectl port-forward -n ns-aiq svc/aiq-backend 8000:8000
```

Open [http://localhost:3000](http://localhost:3000) to access the web UI.

## Configuration

The backend loads a workflow config at startup. Switch configs with `--set`:

| Config file | Description |
|-------------|-------------|
| `configs/config_web_default_llamaindex.yml` | Default -- LlamaIndex backend (no external RAG required) |
| `configs/config_web_frag.yml` | Foundational RAG mode (requires a running RAG service) |

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml
```

## FRAG Integration

To use the Foundational RAG (FRAG) config, you need a running NVIDIA RAG Blueprint deployment. See the [RAG Blueprint Helm deployment guide](https://github.com/NVIDIA-AI-Blueprints/rag/blob/develop/docs/deploy-helm.md) for setup instructions.

### Same-cluster RAG connection

If the RAG Blueprint is deployed in the same Kubernetes cluster, use internal service DNS:

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml \
  --set aiq.apps.backend.env.RAG_SERVER_URL=http://rag-server.<rag-namespace>.svc.cluster.local:8081/v1 \
  --set aiq.apps.backend.env.RAG_INGEST_URL=http://ingestor-server.<rag-namespace>.svc.cluster.local:8082/v1
```

Replace `<rag-namespace>` with the namespace where the RAG Blueprint is deployed.

### External RAG connection

If the RAG service is running outside the cluster:

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml \
  --set aiq.apps.backend.env.RAG_SERVER_URL=http://<rag-host>:8081/v1 \
  --set aiq.apps.backend.env.RAG_INGEST_URL=http://<rag-ingest-host>:8082/v1
```

### Values file approach

For complex overrides, create a values file instead of passing many `--set` flags:

```yaml
# aiq-frag-values.yaml
aiq:
  apps:
    backend:
      env:
        CONFIG_FILE: configs/config_web_frag.yml
        RAG_SERVER_URL: http://rag-server.rag-namespace.svc.cluster.local:8081/v1
        RAG_INGEST_URL: http://ingestor-server.rag-namespace.svc.cluster.local:8082/v1
```

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq -f aiq-frag-values.yaml
```

## Secrets Reference

### Required

| Key | Description |
|-----|-------------|
| `NVIDIA_API_KEY` | API key for NIM inference models |
| `TAVILY_API_KEY` | Tavily API key for web search |
| `DB_USER_NAME` | PostgreSQL username |
| `DB_USER_PASSWORD` | PostgreSQL password |

### Optional

| Key | Description |
|-----|-------------|
| `SERPER_API_KEY` | Serper API key for Google search |
| `JINA_API_KEY` | Jina API key |
| `WANDB_API_KEY` | Weights & Biases API key |
| `NVIDIA_INFERENCE_API_KEY` | Alternative inference key (defaults to `NVIDIA_API_KEY`) |
| `INFERENCE_NVIDIA_API_KEY` | Alternative inference key (defaults to `NVIDIA_API_KEY`) |

### Updating secrets

```bash
kubectl delete secret aiq-credentials -n ns-aiq
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="new-key" \  # pragma: allowlist secret
  --from-literal=TAVILY_API_KEY="new-key" \  # pragma: allowlist secret
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="new-password"  # pragma: allowlist secret

kubectl rollout restart deployment -n ns-aiq aiq-backend aiq-frontend
```

## Upgrade

```bash
helm upgrade aiq deployment-k8s/ -n ns-aiq
```

To upgrade with new image versions:

```bash
helm upgrade aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.image.tag=<new-tag> \
  --set aiq.apps.frontend.image.tag=<new-tag>
```

## Uninstall

```bash
helm uninstall aiq -n ns-aiq

# Optionally remove namespace and secrets
kubectl delete namespace ns-aiq
```

## Troubleshooting

### Pod status

```bash
kubectl get pods -n ns-aiq
kubectl describe pod <pod-name> -n ns-aiq
kubectl get events -n ns-aiq --sort-by='.lastTimestamp'
```

### Logs

```bash
# Backend logs
kubectl logs -n ns-aiq -l component=backend -f

# Frontend logs
kubectl logs -n ns-aiq -l component=frontend -f

# Database init container logs
kubectl logs -n ns-aiq <backend-pod> -c db-init
```

### PVC inspection

```bash
kubectl get pvc -n ns-aiq
kubectl describe pvc aiq-postgres-data -n ns-aiq
```

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImagePullBackOff` | Missing or incorrect image pull secret | Verify `ngc-secret` exists and credentials are valid. Check `kubectl describe pod <pod>`. |
| `CrashLoopBackOff` | Missing credentials or bad config | Check `kubectl logs <pod> -n ns-aiq`. Verify `aiq-credentials` secret has all required keys. |
| Pod stuck in `Pending` | Insufficient cluster resources or PVC not bound | Check `kubectl describe pod <pod>` for scheduling errors. Verify PVC status with `kubectl get pvc -n ns-aiq`. |
| FRAG mode: RAG connection refused | RAG service not reachable | Verify RAG pods are running and service DNS resolves. Test with `kubectl exec` into the backend pod and `curl` the RAG URL. |
| Health check fails | Backend not fully started | Wait for init containers to complete. Check `kubectl logs <pod> -c db-init -n ns-aiq` for database init issues. |
