# AI-Q Kubernetes Deployment

Deploy AI-Q to a Kubernetes cluster using the Helm charts in this repository.

## Repository Structure

```
deployment-k8s/
├── stg/                  # Helm chart for the STG environment
│   ├── Chart.yaml        # Chart definition (depends on ../helm-charts-k8s/aiq)
│   └── values.yaml       # Deployment values for this environment
└── README.md

helm-charts-k8s/
└── aiq/                  # Base application Helm chart
```

The `stg/` chart references `helm-charts-k8s/aiq` as a local file dependency. Both directories must be present at the same level.

## Prerequisites

- Kubernetes cluster (Kind, EKS, GKE, AKS, etc.)
- `kubectl` configured with cluster access
- `helm` v3.x installed
- Required API keys (see [Secrets](#secrets) section)

## Building and Loading Images for Kind

For local development with a [Kind](https://kind.sigs.k8s.io/) cluster, you build images locally and load them directly into the cluster — no registry push required.

### 1. Build the images

Run the following from the **repository root**:

```bash
# Backend
docker build --platform linux/amd64 \
  -f deploy/Dockerfile \
  -t aiq-research-assistant:dev \
  .

# Frontend
docker build --platform linux/amd64 \
  -f frontends/ui/deploy/Dockerfile \
  -t aiq-frontend:dev \
  frontends/ui
```

This produces two local images:
- `aiq-research-assistant:dev` — backend (Python / FastAPI)
- `aiq-frontend:dev` — frontend (Next.js)

### 2. Load the images into Kind

```bash
kind load docker-image aiq-research-assistant:dev --name <your-cluster-name>
kind load docker-image aiq-frontend:dev --name <your-cluster-name>
```

> Run `kind get clusters` if you are unsure of the cluster name.

### 3. Configure values to use the local images

Edit `deployment-k8s/stg/values.yaml` (or pass `--set` flags at deploy time) so the image references match what you loaded:

```yaml
aiq:
  apps:
    backend:
      image:
        repository: aiq-research-assistant
        tag: dev
        pullPolicy: Never      # <-- critical: tells k8s not to pull from a registry
    frontend:
      image:
        repository: aiq-frontend
        tag: dev
        pullPolicy: Never
```

Or pass them inline:

```bash
helm upgrade --install aiq deployment-k8s/stg/ -n aiq --create-namespace \
  --set aiq.apps.backend.image.repository=aiq-research-assistant \
  --set aiq.apps.backend.image.tag=dev \
  --set aiq.apps.backend.image.pullPolicy=Never \
  --set aiq.apps.frontend.image.repository=aiq-frontend \
  --set aiq.apps.frontend.image.tag=dev \
  --set aiq.apps.frontend.image.pullPolicy=Never
```

### 4. Create the credentials secret and deploy

Follow the [Setup](#setup) and [Deploy](#deploy) sections below, then verify with:

```bash
kubectl get pods -n aiq
```

After a rebuild, reload the updated image with `kind load docker-image ...` and restart the affected deployment:

```bash
kubectl rollout restart deployment -n aiq aiq-backend   # or aiq-frontend
```

---

## Setup

> **Note:** If you generated these charts using the blueprint generator, `helm dependency update` was already run automatically. Only run it manually if you re-package or move the charts.

### 1. Create the credentials secret

The deployment reads API keys and database credentials from a Kubernetes Secret named `aiq-credentials`.

```bash
kubectl create secret generic aiq-credentials -n aiq \
  --from-literal=NVIDIA_API_KEY="your-nvidia-api-key" \
  --from-literal=TAVILY_API_KEY="your-tavily-api-key" \
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="your-db-password"
```

Or from environment variables:

```bash
kubectl create secret generic aiq-credentials -n aiq \
  --from-literal=NVIDIA_API_KEY="$NVIDIA_API_KEY" \
  --from-literal=TAVILY_API_KEY="$TAVILY_API_KEY" \
  --from-literal=DB_USER_NAME="$DB_USER_NAME" \
  --from-literal=DB_USER_PASSWORD="$DB_USER_PASSWORD"
```

## Deploy

```bash
helm install aiq deployment-k8s/stg/ -n aiq --create-namespace
```

### Verify

```bash
kubectl get pods -n aiq
```

Expected output:

```
NAME                            READY   STATUS    RESTARTS   AGE
aiq-backend-xxx                 1/1     Running   0          30s
aiq-frontend-xxx                1/1     Running   0          30s
aiq-postgres-xxx                1/1     Running   0          30s
```

## Secrets

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

### Updating Secrets

```bash
kubectl delete secret aiq-credentials -n aiq
kubectl create secret generic aiq-credentials -n aiq \
  --from-literal=NVIDIA_API_KEY="new-key" \
  --from-literal=TAVILY_API_KEY="new-key" \
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="new-password"

kubectl rollout restart deployment -n aiq aiq-backend aiq-frontend
```

## Accessing the Application

```bash
# Frontend UI
kubectl port-forward -n aiq svc/aiq-frontend 3000:3000

# Backend API
kubectl port-forward -n aiq svc/aiq-backend 8000:8000
```

Then open: http://localhost:3000

## Upgrade

```bash
helm upgrade aiq deployment-k8s/stg/ -n aiq
```

## Override Values

```bash
helm upgrade --install aiq deployment-k8s/stg/ -n aiq \
  --set aiq.apps.backend.replicas=2
```

## Uninstall

```bash
helm uninstall aiq -n aiq

# Optionally remove namespace and secrets
kubectl delete namespace aiq
```
