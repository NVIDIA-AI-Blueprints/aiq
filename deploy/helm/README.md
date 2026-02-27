<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q Helm Deployment

This directory contains Helm charts for deploying AI-Q to a Kubernetes cluster.

## Directory Structure

```
deploy/helm/
├── README.md                  # This file — NGC chart install & shared configuration
├── deployment-k8s/            # Source chart wrapper (for repo-based deployments)
│   ├── Chart.yaml             #   Depends on helm-charts-k8s/aiq
│   ├── values.yaml            #   Deployment values
│   └── README.md              #   Source chart instructions & Kind local dev guide
└── helm-charts-k8s/
    └── aiq/                   # Base application Helm chart (templates, helpers)
```

## Deployment Methods

| Method | When to use |
|--------|-------------|
| [NGC Helm chart](#install-from-ngc-helm-repository) | Install a pre-built chart from the NGC Helm repository |
| [Source chart](deployment-k8s/README.md) | You cloned the repository and want to build/deploy from source |

## Prerequisites

- Kubernetes cluster (EKS, GKE, AKS, or a local cluster such as Kind or Minikube)
- `kubectl` configured with cluster access
- `helm` v3.x installed
- NGC API key (`NGC_API_KEY` environment variable)
- Required API keys (see [Secrets](#secrets) below)

## Install from NGC Helm Repository

### 1. Add the NGC Helm repository

```bash
helm repo add <ngc-helm-repo> https://helm.ngc.nvidia.com/<ngc-org>/<ngc-team> \
  --username='$oauthtoken' \
  --password=$NGC_API_KEY

helm repo update <ngc-helm-repo>
```

Replace `<ngc-helm-repo>` with a local name for the repository, and `<ngc-org>/<ngc-team>` with the NGC organization and team provided to you.

### 2. Create the namespace

```bash
kubectl create namespace ns-aiq --dry-run=client -o yaml | kubectl apply -f -
```

### 3. Create secrets

API credentials for the application:

```bash
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="$NGC_API_KEY" \
  --from-literal=TAVILY_API_KEY="$TAVILY_API_KEY" \
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="aiq_dev"
```

Image pull secret for the NGC container registry:

```bash
kubectl create secret docker-registry ngc-secret -n ns-aiq \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=$NGC_API_KEY
```

### 4. Install the chart

**Option A — Fetch then install:**

Download the chart archive first, then install from the local `.tgz` file:

```bash
helm pull <ngc-helm-repo>/<chart-name> --version <version>

helm upgrade --install aiq <chart-name>-<version>.tgz -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret'
```

**Option B — Install directly from the repository:**

```bash
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret'
```

Replace `<chart-name>` and `<version>` with the values provided to you (for example, `aiq-web` and `2603.7.0`).

### Override values

Pass additional `--set` flags to customize the deployment:

```bash
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret' \
  --set aiq.apps.backend.image.tag=<tag>
```

Or supply a custom values file:

```bash
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  -f custom-values.yaml
```

### Inspect default values

To see what values a chart supports before installing:

```bash
# From the repository
helm show values <ngc-helm-repo>/<chart-name> --version <version>

# From a local .tgz file
helm show values <chart-name>-<version>.tgz
```

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

### Upgrade

To upgrade an existing release to a newer chart version:

```bash
helm repo update <ngc-helm-repo>

helm upgrade aiq <ngc-helm-repo>/<chart-name> --version <new-version> -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret'
```

### Uninstall

```bash
helm uninstall aiq -n ns-aiq

# Optionally remove namespace and secrets
kubectl delete namespace ns-aiq
```

## Configuration

The backend loads a workflow config at startup. Switch configs with `--set`:

| Config file | Description |
|-------------|-------------|
| `configs/config_web_default_llamaindex.yml` | Default — LlamaIndex backend (no external RAG required) |
| `configs/config_web_frag.yml` | Foundational RAG mode (requires a running RAG service) |

```bash
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret' \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml
```

## FRAG Integration

To use the Foundational RAG (FRAG) config, you need a running NVIDIA RAG Blueprint deployment. See the [RAG Blueprint Helm deployment guide](https://github.com/NVIDIA-AI-Blueprints/rag/blob/develop/docs/deploy-helm.md) for setup instructions.

### Same-cluster RAG connection

If the RAG Blueprint is deployed in the same Kubernetes cluster, use internal service DNS:

```bash
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret' \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml \
  --set aiq.apps.backend.env.RAG_SERVER_URL=http://rag-server.<rag-namespace>.svc.cluster.local:8081/v1 \
  --set aiq.apps.backend.env.RAG_INGEST_URL=http://ingestor-server.<rag-namespace>.svc.cluster.local:8082/v1
```

Replace `<rag-namespace>` with the namespace where the RAG Blueprint is deployed.

### External RAG connection

If the RAG service is running outside the cluster:

```bash
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret' \
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
helm upgrade --install aiq <ngc-helm-repo>/<chart-name> --version <version> -n ns-aiq \
  --wait --timeout 10m \
  -f aiq-frag-values.yaml
```

## Secrets

### Required

| Key | Description |
|-----|-------------|
| `NVIDIA_API_KEY` | API key for NIM inference models |
| `TAVILY_API_KEY` | Tavily API key for web search |
| `DB_USER_NAME` | PostgreSQL username (default: `aiq`) |
| `DB_USER_PASSWORD` | PostgreSQL password (default: `aiq_dev`) |

### Optional

| Key | Description |
|-----|-------------|
| `SERPER_API_KEY` | Serper API key for Google search |
| `JINA_API_KEY` | Jina API key |
| `WANDB_API_KEY` | Weights & Biases API key |

### Updating secrets

```bash
kubectl delete secret aiq-credentials -n ns-aiq
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="new-key" \  # pragma: allowlist secret
  --from-literal=TAVILY_API_KEY="new-key" \  # pragma: allowlist secret
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="aiq_dev"

kubectl rollout restart deployment -n ns-aiq aiq-backend aiq-frontend
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

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImagePullBackOff` | Missing or incorrect image pull secret | Verify `ngc-secret` exists and credentials are valid. Check `kubectl describe pod <pod>`. |
| `CrashLoopBackOff` | Missing credentials or bad config | Check `kubectl logs <pod> -n ns-aiq`. Verify `aiq-credentials` secret has all required keys. |
| Pod stuck in `Pending` | Insufficient cluster resources or PVC not bound | Check `kubectl describe pod <pod>` for scheduling errors. Verify PVC status with `kubectl get pvc -n ns-aiq`. |
| FRAG mode: RAG connection refused | RAG service not reachable | Verify RAG pods are running and service DNS resolves. Test with `kubectl exec` into the backend pod and `curl` the RAG URL. |
| Health check fails | Backend not fully started | Wait for init containers to complete. Check `kubectl logs <pod> -c db-init -n ns-aiq` for database init issues. |

## Source Chart Deployment

For deploying from the cloned repository (building from source charts, local images, NGC images), see the [deployment-k8s README](deployment-k8s/README.md).
