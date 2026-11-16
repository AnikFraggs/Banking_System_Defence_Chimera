#!/usr/bin/env bash
# Turns the "untested k8s scaffold" into a checked one: offline validation, then a real kind cluster,
# locally built images, the real card artifact mounted, and a pass/fail smoke test.
# Run from the repo root:  bash k8s/k8s_smoke.sh      (needs docker, kind, kubectl; kubeconform optional)
set -euo pipefail

K8S_DIR="${K8S_DIR:-k8s}"                         # manifests directory
CLUSTER="${CLUSTER:-chimera}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$PWD/fraud-gate/artifacts}"
GATE_SVC="${GATE_SVC:-fraud-gate}"                # ASSUMPTION: service name/port in your manifests
GATE_PORT="${GATE_PORT:-8001}"
NAMESPACE="${NAMESPACE:-default}"

# EDIT: "image-tag|docker build context|Dockerfile". Tags must match the manifests (grep 'image:' k8s/*.yaml).
IMAGES=(
  "chimera-platform-api:local|platform-api|platform-api/Dockerfile"
  "chimera-fraud-gate:local|fraud-gate|fraud-gate/Dockerfile"
  "chimera-ai-brain:local|ai-brain|ai-brain/Dockerfile"
)

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing tool: $1"; exit 2; }; }
need docker; need kubectl; need kind; need python3

echo "== 1/6 offline validation (no cluster needed)"
if command -v kubeconform >/dev/null 2>&1; then
  kubeconform -strict -ignore-missing-schemas -summary -r "$K8S_DIR"
else
  echo "kubeconform not installed; falling back to client-side parse only"
  kubectl apply --dry-run=client --validate=false -R -f "$K8S_DIR" >/dev/null
fi

echo "== 2/6 guard: fraud-gate must not mount an emptyDir at /artifacts (that means no model => fail-closed)"
python3 - "$K8S_DIR" <<'PY'
import sys, glob, yaml
bad = []
for f in glob.glob(sys.argv[1] + "/**/*.y*ml", recursive=True):
    for d in yaml.safe_load_all(open(f, encoding="utf-8")):
        if not isinstance(d, dict) or d.get("kind") not in ("Deployment", "StatefulSet"):
            continue
        spec = d["spec"]["template"]["spec"]
        mounts = {m["name"] for c in spec.get("containers", []) for m in c.get("volumeMounts", []) if m.get("mountPath") == "/artifacts"}
        for v in spec.get("volumes", []):
            if v["name"] in mounts and "emptyDir" in v:
                bad.append(f"{f}: {d['metadata']['name']} volume '{v['name']}' is an emptyDir")
if bad:
    print("\n".join(bad)); sys.exit(1)
print("ok")
PY

[ -f "$ARTIFACTS_DIR/creditcard_hgb.joblib" ] || { echo "no $ARTIFACTS_DIR/creditcard_hgb.joblib: the gate would fail closed"; exit 3; }

echo "== 3/6 cluster"
if ! kind get clusters | grep -qx "$CLUSTER"; then
  export ARTIFACTS_DIR
  envsubst < "$K8S_DIR/kind-config.yaml" | kind create cluster --name "$CLUSTER" --config -
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "== 4/6 build + load images (kind cannot pull ':local' tags)"
for spec in "${IMAGES[@]}"; do
  IFS='|' read -r tag ctx dockerfile <<<"$spec"
  [ -f "$dockerfile" ] || { echo "Dockerfile not found: $dockerfile (edit IMAGES)"; exit 2; }
  docker build -t "$tag" -f "$dockerfile" "$ctx"
  kind load docker-image "$tag" --name "$CLUSTER"
done

echo "== 5/6 apply + wait"
kubectl apply -R -f "$K8S_DIR"
kubectl -n "$NAMESPACE" rollout status deploy --timeout=180s || { kubectl -n "$NAMESPACE" get pods -o wide; exit 4; }

echo "== 6/6 smoke: gate is ready AND reports a loaded model"
kubectl -n "$NAMESPACE" port-forward "svc/$GATE_SVC" "$GATE_PORT:$GATE_PORT" >/tmp/pf.log 2>&1 &
PF=$!; trap 'kill $PF 2>/dev/null || true' EXIT
for i in $(seq 1 30); do curl -fsS "http://127.0.0.1:$GATE_PORT/ready" >/dev/null 2>&1 && break; sleep 1; [ "$i" = 30 ] && { echo "/ready never became 200"; exit 5; }; done
curl -fsS "http://127.0.0.1:$GATE_PORT/metrics" | grep -Eq '^chimera_fraud_gate_model_loaded(\{[^}]*\})? 1(\.0)?$' \
  || { echo "chimera_fraud_gate_model_loaded is not 1: model not loaded (fail-closed to CHALLENGE)"; exit 6; }
echo "PASS: manifests validate, images resolve, artifact is mounted, model loaded"
