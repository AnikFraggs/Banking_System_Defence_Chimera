# CHIMERA Checkout Shield - Kubernetes manifests

**Status: UNTESTED STARTING POINT.** These plain-YAML manifests (no Helm) have
**never been applied to a cluster**. They are a scaffold to adapt, not a verified
deployment. Treat every value as a demo default and review before use.

**Deferred to the deployment phase.** Together with `infra/terraform/` (also
deferred), this overlay is the intended later upgrade path. The system that
actually runs and is measured today is the local `compose.yaml` stack.

**SANDBOX ONLY.** This is a defensive payment reference app. Never use real
cards, real cardholder data, or real PayPal accounts. PayPal runs in `stub` mode
by default; sandbox HTTP requires an operator to opt in with PayPal *sandbox*
test credentials only.

## Local kind validation (2026-11-16)

`python deploy/k8s/validate_local.py` structurally checks the local overlay (20 resources). This is **not** Kubernetes API validation. The attempted `--run` stopped because `kind` is absent; no cluster was changed.

After installing `kind`, `kubectl`, Docker and Python/PyYAML, run `python deploy/k8s/validate_local.py --run`. It builds and loads all five local images without a registry, creates only `chimera-observability`, uses a separate kubeconfig, and refuses an existing cluster/config. It renders read-only card and deployed L4 host mounts, generates throwaway secrets in memory, forces stub payments, waits for deployments and probes card readiness and ai-brain health. It does not deploy ingress/HPA or prove settlement under Kubernetes load. The cluster remains for inspection; cleanup is manual.

The base model `emptyDir` manifests remain scaffolds for non-kind environments; provide production-appropriate artifact volumes yourself. Never apply the example secret unchanged or recursively apply every YAML file.

## What is here

| File | Contents |
| --- | --- |
| `namespace.yaml` | Namespace `chimera` |
| `configmap.yaml` | Non-secret env (`chimera-config`), mirrors `compose.yaml` / `.env.example` |
| `secret.example.yaml` | Secret template (`chimera-secrets`) with placeholders. **DO NOT COMMIT real values.** |
| `postgres.yaml` | Deployment + Service (5432), `postgres:15-alpine` |
| `redis.yaml` | Deployment + Service (6379), `redis:7-alpine` |
| `fraud-gate.yaml` | Deployment + Service (REST 8001), `chimera-fraud-gate:local` |
| `fraud-gate-grpc.yaml` | Deployment + Service (gRPC 50051), `chimera-fraud-gate:local` |
| `fraud-gate-worker.yaml` | Deployment + internal metrics Service (8084), `chimera-fraud-gate:local` |
| `platform-api.yaml` | Deployment + Service (8080), `chimera-platform-api:local` |
| `web.yaml` | Deployment + Service (80), `chimera-checkout-web:local` |
| `ingress.yaml` | ingress-nginx routing `/api` -> platform-api, `/` -> web |
| `hpa.yaml` | platform-api CPU autoscaler (target 70%, 2-6 replicas) |

## Images must be pushed to a registry

The `chimera-*:local` tags are **local build tags** produced by `compose.yaml`.
They will not resolve inside a cluster. Build each image, push it to a registry
your cluster can pull from, and replace the `image:` field (and add
`imagePullSecrets` if the registry is private). Example:

```
docker build -t <registry>/chimera-platform-api:<tag> .
docker build -t <registry>/chimera-fraud-gate:<tag> ./fraud-gate
docker build -t <registry>/chimera-checkout-web:<tag> ./web
docker push <registry>/chimera-platform-api:<tag>   # etc.
```

The `web` image bakes `VITE_*` build args (see `web/Dockerfile`); set them at
build time, not as runtime env.

## Secrets

```
cp secret.example.yaml secret.yaml
# edit secret.yaml: replace every CHANGE_ME with a throwaway LOCAL/DEMO value
# add secret.yaml to .gitignore; NEVER commit real values
```

`POSTGRES_PASSWORD` and `SPRING_DATASOURCE_PASSWORD` must match. `AUDIT_HMAC_KEY`
should be a long random value for any persistent/shared deployment. PayPal
credential fields stay empty unless you explicitly configure sandbox test
accounts.

## Suggested apply order

```
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secret.yaml          # your local copy, not the .example
kubectl apply -f postgres.yaml -f redis.yaml
kubectl apply -f fraud-gate.yaml -f fraud-gate-grpc.yaml -f fraud-gate-worker.yaml
kubectl apply -f platform-api.yaml -f web.yaml
kubectl apply -f ingress.yaml -f hpa.yaml
```

## Known gaps / things to verify (untested)

- **Ephemeral storage:** postgres and redis use `emptyDir`. Data is lost when a
  pod is removed. For persistence, convert them to StatefulSets with PVCs.
- **Fraud gate model artifact:** `/artifacts` is an `emptyDir`. With no model,
  `/ready` returns **503** and the fraud-gate pod stays **NotReady** by design
  (fail-closed CHALLENGE scoring). Supply the operator model via a PVC, an init
  container, or a baked image before expecting CAPTURE. Liveness uses
  `/openapi.json` so a missing model does not crash-loop the pod.
- **Fraud gate `/metrics` EXISTS (verified 2026-11-16):** `fraud-gate/app/main.py`
  exposes `GET /metrics`, and `observability/prometheus.yml` actively scrapes
  fraud-gate, fraud-gate-grpc and fraud-gate-worker (all targets `up`). The old
  "scraping commented out" note is superseded.
- **platform-api actuator:** `application.yml` now exposes
  `health,info,prometheus,metrics` and `micrometer-registry-prometheus` is in the
  pom, so `/actuator/health` (probes) and `/actuator/prometheus` (observability)
  are available. The local compose observability stack was verified live on
  2026-11-16 (10/10 Prometheus targets up, Grafana datasource OK, 4 provisioned
  dashboards); the **Kubernetes** observability wiring remains untested.
- **Worker has no Service:** it consumes Redis streams and listens on no port,
  so no Service/readiness probe is defined. Its liveness probe is a best-effort
  `/proc/1/cmdline` check (the slim Python image has no `pgrep`).
- **Ingress + HPA prerequisites:** ingress-nginx and metrics-server must be
  installed. Replace the placeholder host `chimera-checkout.local` and enable TLS.
- **gRPC probes** are TCP-socket checks (no HTTP health endpoint on the gRPC
  server).

Nothing here has been load-tested or benchmarked. Resource requests/limits and
the HPA target are sensible demo guesses, not measured results.