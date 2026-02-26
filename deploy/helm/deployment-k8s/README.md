# AI-Q Kubernetes Deployment

Deploy AI-Q to a Kubernetes cluster using the Helm charts in this repository.

## Repository Structure

```
deployment-k8s/
├── Chart.yaml        # Chart definition (depends on ../helm-charts-k8s/aiq)
├── values.yaml       # Deployment values
└── README.md

helm-charts-k8s/
└── aiq/              # Base application Helm chart
```

The `deployment-k8s/` chart references `helm-charts-k8s/aiq` as a local file dependency. Both directories must be present at the same level.

## Prerequisites

- Kubernetes cluster (EKS, GKE, AKS, etc.) or local cluster (Kind, Minikube)
- `kubectl` configured with cluster access
- `helm` v3.x installed
- Required API keys (see [Secrets](#secrets) section)

## Setup

### 1. Create the credentials secret

The deployment reads API keys and database credentials from a Kubernetes Secret named `aiq-credentials`.

```bash
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="your-nvidia-api-key" \
  --from-literal=TAVILY_API_KEY="your-tavily-api-key" \
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="your-db-password"
```

Or from environment variables:

```bash
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="$NVIDIA_API_KEY" \
  --from-literal=TAVILY_API_KEY="$TAVILY_API_KEY" \
  --from-literal=DB_USER_NAME="$DB_USER_NAME" \
  --from-literal=DB_USER_PASSWORD="$DB_USER_PASSWORD"
```

## Image Pull Secrets

If you are pulling pre-built images from the NGC container registry (`nvcr.io`), create a Docker registry secret:

```bash
kubectl create secret docker-registry ngc-secret -n ns-aiq \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password="<YOUR_NGC_API_KEY>"
```

Then include the secret in your deploy command:

```bash
helm dependency update deployment-k8s/
helm install aiq deployment-k8s/ -n ns-aiq --create-namespace \
  --set aiq.apps.backend.imagePullSecrets[0].name=ngc-secret \
  --set aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret \
  --set aiq.apps.backend.image.repository=nvcr.io/nvidia/blueprint/aiq-agent \
  --set aiq.apps.frontend.image.repository=nvcr.io/nvidia/blueprint/aiq-frontend
```

## Deploy

```bash
helm dependency update deployment-k8s/
helm install aiq deployment-k8s/ -n ns-aiq --create-namespace
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

### Health Check

Once all pods are running, verify the backend is responding:

```bash
kubectl port-forward -n ns-aiq svc/aiq-backend 8000:8000 &
curl http://localhost:8000/health
```

The backend API docs are available at `http://localhost:8000/docs` while the port-forward is active.

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
kubectl delete secret aiq-credentials -n ns-aiq
kubectl create secret generic aiq-credentials -n ns-aiq \
  --from-literal=NVIDIA_API_KEY="new-key" \
  --from-literal=TAVILY_API_KEY="new-key" \
  --from-literal=DB_USER_NAME="aiq" \
  --from-literal=DB_USER_PASSWORD="new-password"

kubectl rollout restart deployment -n ns-aiq aiq-backend aiq-frontend
```

## Accessing the Application

```bash
# Frontend UI
kubectl port-forward -n ns-aiq svc/aiq-frontend 3000:3000

# Backend API
kubectl port-forward -n ns-aiq svc/aiq-backend 8000:8000
```

Then open: http://localhost:3000

## Upgrade

```bash
helm upgrade aiq deployment-k8s/ -n ns-aiq
```

## Override Values

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.replicas=2
```

## Configuration

The backend loads a workflow config at startup. Switch configs with `--set`:

| Config file | Description |
|-------------|-------------|
| `configs/config_web_default_llamaindex.yml` | Default — LlamaIndex backend (no external RAG required) |
| `configs/config_web_frag.yml` | Foundational RAG mode (requires a running RAG service) |

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml
```

## FRAG Integration

To use the Foundational RAG (FRAG) config, you need a running NVIDIA RAG Blueprint deployment. See the [RAG Blueprint Helm deployment guide](https://github.com/NVIDIA-AI-Blueprints/rag/blob/develop/docs/deploy-helm.md) for setup instructions.

### Same-Cluster RAG Connection

If the RAG Blueprint is deployed in the same Kubernetes cluster, use internal service DNS:

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml \
  --set aiq.apps.backend.env.RAG_SERVER_URL=http://rag-server.<rag-namespace>.svc.cluster.local:8081/v1 \
  --set aiq.apps.backend.env.RAG_INGEST_URL=http://ingestor-server.<rag-namespace>.svc.cluster.local:8082/v1
```

Replace `<rag-namespace>` with the namespace where the RAG Blueprint is deployed.

### External RAG Connection

If the RAG service is running outside the cluster:

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq \
  --set aiq.apps.backend.env.CONFIG_FILE=configs/config_web_frag.yml \
  --set aiq.apps.backend.env.RAG_SERVER_URL=http://<rag-host>:8081/v1 \
  --set aiq.apps.backend.env.RAG_INGEST_URL=http://<rag-ingest-host>:8082/v1
```

### Values File Approach

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

## Troubleshooting

### Pod Status

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
```

### PVC Inspection

```bash
kubectl get pvc -n ns-aiq
kubectl describe pvc aiq-postgres-data -n ns-aiq
```

### Image Pull Secret Verification

```bash
kubectl get secret ngc-secret -n ns-aiq -o yaml
kubectl get pods -n ns-aiq -o jsonpath='{.items[*].spec.imagePullSecrets}'
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImagePullBackOff` | Missing or incorrect image pull secret | Verify `ngc-secret` exists and credentials are valid. Check `kubectl describe pod <pod>`. |
| `CrashLoopBackOff` | Missing credentials or bad config | Check `kubectl logs <pod> -n ns-aiq`. Verify `aiq-credentials` secret has all required keys. |
| Pod stuck in `Pending` | Insufficient cluster resources or PVC not bound | Check `kubectl describe pod <pod>` for scheduling errors. Verify PVC status with `kubectl get pvc -n ns-aiq`. |
| FRAG mode: RAG connection refused | RAG service not reachable | Verify RAG pods are running and service DNS resolves. Test with `kubectl exec` into the backend pod and `curl` the RAG URL. |
| Health check fails | Backend not fully started | Wait for init containers to complete. Check `kubectl logs <pod> -c db-init -n ns-aiq` for database init issues. |

## Uninstall

```bash
helm uninstall aiq -n ns-aiq

# Optionally remove namespace and secrets
kubectl delete namespace ns-aiq
```

---

## Getting Started with Minimal K8s (Kind)

For local development with a [Kind](https://kind.sigs.k8s.io/) cluster, you can build images locally and load them directly into the cluster — no registry push required.

### 1. Build the images

Run the following from the **repository root**:

```bash
# Backend
docker build --platform linux/amd64 \
  -f deploy/Dockerfile \
  -t aiq-agent:dev \
  .

# Frontend
docker build --platform linux/amd64 \
  -f frontends/ui/deploy/Dockerfile \
  -t aiq-frontend:dev \
  frontends/ui
```

This produces two local images:
- `aiq-agent:dev` — backend (Python / FastAPI)
- `aiq-frontend:dev` — frontend (Next.js)

### 2. Load the images into Kind

```bash
kind load docker-image aiq-agent:dev --name <your-cluster-name>
kind load docker-image aiq-frontend:dev --name <your-cluster-name>
```

> Run `kind get clusters` if you are unsure of the cluster name.

### 3. Configure values to use the local images

Edit `deployment-k8s/values.yaml` (or pass `--set` flags at deploy time) so the image references match what you loaded:

```yaml
aiq:
  apps:
    backend:
      image:
        repository: aiq-agent
        tag: dev
        pullPolicy: IfNotPresent
    frontend:
      image:
        repository: aiq-frontend
        tag: dev
        pullPolicy: IfNotPresent
```

Or pass them inline during deployment:

```bash
helm upgrade --install aiq deployment-k8s/ -n ns-aiq --create-namespace \
  --set aiq.apps.backend.image.repository=aiq-agent \
  --set aiq.apps.backend.image.tag=dev \
  --set aiq.apps.backend.image.pullPolicy=IfNotPresent \
  --set aiq.apps.frontend.image.repository=aiq-frontend \
  --set aiq.apps.frontend.image.tag=dev \
  --set aiq.apps.frontend.image.pullPolicy=IfNotPresent
```

### 4. Create the credentials secret and deploy

Follow the main [Setup](#setup) section to create your secrets, then deploy.

After a rebuild, reload the updated image with `kind load docker-image ...` and restart the affected deployment:

```bash
kubectl rollout restart deployment -n ns-aiq aiq-backend   # or aiq-frontend
```
