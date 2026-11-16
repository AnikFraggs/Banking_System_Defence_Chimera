from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLUSTER = "chimera-observability"
FILES = ("namespace", "configmap", "postgres", "redis", "fraud-gate", "fraud-gate-grpc", "fraud-gate-worker", "ai-brain", "platform-api", "bff-express", "web")
IMAGES = ("chimera-platform-api:local", "chimera-fraud-gate:local", "chimera-ai-brain:local", "chimera-bff:local", "chimera-checkout-web:local")


def render():
    documents = []
    for name in FILES:
        documents.extend(yaml.safe_load_all((ROOT / f"deploy/k8s/{name}.yaml").read_text(encoding="utf-8")))
    for doc in documents:
        if doc["kind"] != "Namespace" and doc["metadata"].get("namespace") != "chimera":
            raise ValueError("unexpected namespace")
        if doc["kind"] != "Deployment":
            continue
        doc["spec"]["replicas"] = 1
        spec = doc["spec"]["template"]["spec"]
        name = doc["metadata"]["name"]
        container = spec["containers"][0]
        if name in ("fraud-gate", "fraud-gate-grpc"):
            spec["volumes"] = [{"name": "artifacts", "hostPath": {"path": "/chimera-card", "type": "Directory"}}]
            for mount in container["volumeMounts"]:
                mount["readOnly"] = True
        if name == "platform-api":
            spec["volumes"] = [{"name": "l4", "hostPath": {"path": "/chimera-l4", "type": "Directory"}}]
            container["volumeMounts"] = [{"name": "l4", "mountPath": "/opt/chimera/l4", "readOnly": True}]
            container.setdefault("env", []).extend({"name": k, "value": v} for k, v in {
                "L4_SEMANTIC_MODEL_PATH": "/opt/chimera/l4/model.int8.onnx",
                "L4_SEMANTIC_VOCAB_PATH": "/opt/chimera/l4/vocab.txt",
                "L4_SEMANTIC_TIMEOUT_MS": "250", "L4_SEMANTIC_THRESHOLD": "0.65",
                "PAYPAL_MODE": "stub"}.items())
    return documents


def main():
    parser = argparse.ArgumentParser(description="Offline structure checks by default; --run creates a dedicated local kind sandbox.")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    documents = render()
    config = next(d for d in documents if d["kind"] == "ConfigMap")["data"]
    if config["PAYPAL_MODE"] != "stub":
        raise SystemExit("only stub payments are allowed")
    for deployment in (d for d in documents if d["kind"] == "Deployment"):
        spec = deployment["spec"]["template"]["spec"]
        volumes = {v["name"]: v for v in spec.get("volumes", [])}
        for container in spec["containers"]:
            for mount in container.get("volumeMounts", []):
                if mount["mountPath"] in ("/artifacts", "/opt/chimera/l4"):
                    if "hostPath" not in volumes[mount["name"]] or not mount.get("readOnly"):
                        raise ValueError("model mount must be explicit and read-only")
    print(f"PASS: {len(documents)} rendered resources structurally checked; Kubernetes API validation NOT_MEASURED", flush=True)
    if not args.run:
        return
    for tool in ("kind", "kubectl", "docker"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is missing; no cluster was changed")
    card = ROOT / "fraud-gate/artifacts"
    l4 = ROOT / "fraud-gate/training/artifacts/l4_semantic_guard"
    for path in (card / "creditcard_hgb.joblib", l4 / "model.int8.onnx", l4 / "vocab.txt"):
        if not path.is_file():
            raise SystemExit(f"required model artifact missing: {path}")
    clusters = subprocess.check_output(["kind", "get", "clusters"], text=True).splitlines()
    if CLUSTER in clusters:
        raise SystemExit("dedicated cluster already exists; refusing to modify it implicitly")
    output = ROOT / "build-check"
    kubeconfig = output / "kind-observability.kubeconfig"
    if kubeconfig.exists():
        raise SystemExit("dedicated kubeconfig already exists; refusing to overwrite")
    output.mkdir(exist_ok=True)
    kind_config = {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "nodes": [{"role": "control-plane", "extraMounts": [{"hostPath": str(card), "containerPath": "/chimera-card", "readOnly": True}, {"hostPath": str(l4), "containerPath": "/chimera-l4", "readOnly": True}]}]}
    subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"), "build", "platform-api", "fraud-gate", "ai-brain", "bff-express", "web"], check=True)
    subprocess.run(["kind", "create", "cluster", "--name", CLUSTER, "--kubeconfig", str(kubeconfig), "--config", "-"], input=yaml.safe_dump(kind_config), text=True, check=True)
    subprocess.run(["kind", "load", "docker-image", *IMAGES, "--name", CLUSTER], check=True)
    kube = ["kubectl", "--kubeconfig", str(kubeconfig), "--context", "kind-" + CLUSTER]
    secret = yaml.safe_load((ROOT / "deploy/k8s/secret.example.yaml").read_text(encoding="utf-8"))
    password = secrets.token_urlsafe(32)
    secret["stringData"].update(POSTGRES_PASSWORD=password, SPRING_DATASOURCE_PASSWORD=password, AUDIT_HMAC_KEY=secrets.token_hex(32), MANAGER_AUTH_KEY=secrets.token_hex(32))
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID"):
        secret["stringData"][key] = ""
    subprocess.run([*kube, "apply", "-f", "-"], input=yaml.safe_dump(documents[0]), text=True, check=True)
    subprocess.run([*kube, "apply", "-f", "-"], input=yaml.safe_dump_all([secret, *documents[1:]]), text=True, check=True, stdout=subprocess.DEVNULL)
    for doc in documents:
        if doc["kind"] == "Deployment":
            subprocess.run([*kube, "-n", "chimera", "rollout", "status", "deployment/" + doc["metadata"]["name"], "--timeout=240s"], check=True)
    checks = {
        "fraud-gate": "import json,urllib.request; d=json.load(urllib.request.urlopen('http://localhost:8001/ready')); assert d['model_loaded'] is True",
        "ai-brain": "import urllib.request; assert urllib.request.urlopen('http://localhost:8000/health').status == 200",
    }
    for deployment, code in checks.items():
        subprocess.run([*kube, "-n", "chimera", "exec", "deployment/" + deployment, "--", "python", "-c", code], check=True)
    print(json.dumps({"cluster": CLUSTER, "rollouts": "passed", "card_model_ready": True, "ai_brain_health": True, "settlement_load": "NOT_MEASURED", "ingress_hpa": "NOT_DEPLOYED", "cleanup": "manual; cluster deliberately retained"}))


if __name__ == "__main__":
    main()
