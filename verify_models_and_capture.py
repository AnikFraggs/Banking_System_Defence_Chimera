#!/usr/bin/env python3
import json
from pathlib import Path
import joblib

def run_probe():
    results = []

    # 1. Verify Card HGB Artifact
    hgb_path = Path("fraud-gate/artifacts/creditcard_hgb.joblib")
    hgb_meta = Path("fraud-gate/artifacts/creditcard_hgb.metadata.json")
    if hgb_path.exists() and hgb_meta.exists():
        bundle = joblib.load(hgb_path)
        meta = json.loads(hgb_meta.read_text(encoding="utf-8"))
        results.append((
            "G1. Card HGB Artifact",
            "SUCCESS",
            f"Loaded ({meta['data_source']}, synthetic={bundle['synthetic']}, PR-AUC={meta['metrics']['pr_auc']})"
        ))
    else:
        results.append(("G1. Card HGB Artifact", "FAILURE", "Missing creditcard_hgb.joblib or metadata.json"))

    # 2. Verify L4 INT8 ONNX Guard + Recall Improvement
    l4_dir = Path("defense-pipeline/src/main/resources/models/l4_semantic_guard")
    onnx_file = l4_dir / "model.int8.onnx"
    vocab_file = l4_dir / "vocab.txt"
    meta_file = l4_dir / "metadata.json"
    if onnx_file.exists() and vocab_file.exists() and meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        rec = meta["int8_onnx_holdout"]["recall"]
        status = "SUCCESS" if rec > 0.151 else "FAILURE"
        results.append((
            "G2. L4 INT8 ONNX Guard",
            status,
            f"Measured ONNX recall={rec*100:.1f}% vs 15.1% regex baseline (F1={meta['int8_onnx_holdout']['f1']})"
        ))
    else:
        results.append(("G2. L4 INT8 ONNX Guard", "FAILURE", f"Missing model.int8.onnx, vocab.txt, or metadata.json in {l4_dir}"))

    print(f"{'CHECK':<28} | {'STATUS':<8} | DETAILS")
    print("-" * 95)
    for name, status, detail in results:
        print(f"{name:<28} | {status:<8} | {detail}")

if __name__ == "__main__":
    run_probe()
