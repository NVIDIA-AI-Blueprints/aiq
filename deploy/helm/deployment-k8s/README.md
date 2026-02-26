# AI-Q Kubernetes Deployment — Source Chart

Deploy AI-Q from the cloned repository using the local Helm chart.

> **Looking to install from the NGC Helm repository?** See the [Helm README](../README.md#install-from-ngc-helm-repository) instead.

## Prerequisites

- Kubernetes cluster (EKS, GKE, AKS, etc.) or local cluster (Kind, Minikube)
- `kubectl` configured with cluster access
- `helm` v3.x installed
- Secrets created per the [Helm README — Setup](../README.md#3-create-secrets) (credentials and image pull secrets)

## Deploy

```bash
helm dependency update deployment-k8s/
helm install aiq deployment-k8s/ -n ns-aiq --create-namespace
```

If pulling images from NGC, include the image pull secret and repository overrides:

```bash
helm dependency update deployment-k8s/
helm install aiq deployment-k8s/ -n ns-aiq --create-namespace \
  --set 'aiq.apps.backend.imagePullSecrets[0].name=ngc-secret' \
  --set 'aiq.apps.frontend.imagePullSecrets[0].name=ngc-secret' \
  --set aiq.apps.backend.image.repository=nvcr.io/nvidia/blueprint/aiq-agent \
  --set aiq.apps.frontend.image.repository=nvcr.io/nvidia/blueprint/aiq-frontend
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

```bash
kubectl port-forward -n ns-aiq svc/aiq-backend 8000:8000 &
curl http://localhost:8000/health
```

## Configuration, FRAG, Secrets, and Access

These topics apply to all deployment methods and are documented in the [Helm README](../README.md):

- [Configuration](../README.md#configuration) — switching workflow configs (LlamaIndex vs FRAG)
- [FRAG Integration](../README.md#frag-integration) — connecting to a RAG Blueprint deployment
- [Secrets](../README.md#secrets) — required API keys and database credentials (`DB_USER_NAME=aiq`, `DB_USER_PASSWORD=aiq_dev` by default)
- [Access the application](../README.md#access-the-application) — port-forwarding to the UI and API

## Upgrade

```bash
helm upgrade aiq deployment-k8s/ -n ns-aiq
```

## Uninstall

```bash
helm uninstall aiq -n ns-aiq

# Optionally remove namespace and secrets
kubectl delete namespace ns-aiq
```

## Troubleshooting

See the [Helm README — Troubleshooting](../README.md#troubleshooting) for common issues (pod status, logs, image pull errors, FRAG connection issues).

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

Follow the [Helm README — Setup](../README.md#2-create-the-namespace) to create your namespace and secrets, then deploy.

After a rebuild, reload the updated image with `kind load docker-image ...` and restart the affected deployment:

```bash
kubectl rollout restart deployment -n ns-aiq aiq-backend   # or aiq-frontend
```
