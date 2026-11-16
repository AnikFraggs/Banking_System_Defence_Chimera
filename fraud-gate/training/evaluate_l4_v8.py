from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from sklearn.metrics import average_precision_score, roc_auc_score
from transformers import AutoTokenizer


def read_rows(path):
    with path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    texts = [r.get("text", r.get("payload", "")) for r in rows]
    labels = np.asarray([r["label"] for r in rows], dtype=int)
    if not texts or not all(texts) or set(labels) != {0, 1}:
        raise ValueError(f"{path}: requires text and both binary labels")
    return texts, labels


def cutoff(scores, labels, max_fpr=.02):
    return max(float(np.sort(s[y == 0])[::-1][math.floor(max_fpr * sum(y == 0))]) for s, y in zip(scores, labels))


def wilson(k, n):
    z = 1.959963984540054
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [center - radius, center + radius]


def metrics(scores, labels, cut):
    pred = scores > cut
    tp, fp = int(sum(pred & (labels == 1))), int(sum(pred & (labels == 0)))
    pos, neg = int(sum(labels == 1)), int(sum(labels == 0))
    return {"n_pos": pos, "n_neg": neg, "tp": tp, "fp": fp, "recall": tp / pos, "fpr": fp / neg,
            "recall_wilson95": wilson(tp, pos), "fpr_wilson95": wilson(fp, neg),
            "roc_auc": float(roc_auc_score(labels, scores)), "average_precision": float(average_precision_score(labels, scores))}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--authorized-data", action="store_true")
    args = parser.parse_args()
    if not args.authorized_data:
        raise SystemExit("--authorized-data is required")
    root = args.root
    out = root / "build-check/l4_v8"
    if (out / "paired_evaluation.json").exists() or (out / "calibration_lock.json").exists():
        raise SystemExit("evaluation already locked; refuse implicit test retuning")
    protocol = json.loads((out / "protocol.json").read_text())
    manifest = json.loads((out / "data_manifest.json").read_text())
    for path, expected in manifest["locked"].items():
        if digest(root / path) != expected:
            raise SystemExit(f"locked data changed: {path}")
    models = {"v6": root / protocol["baseline"], "v8": out / "out_v8"}
    base = root / "datasets/new_custom_datasets/out/v5"
    cal_paths = {"internal": base / "l4_v5_calib.jsonl", "external": base / "l4_v5_external_calib.jsonl", "new": out / "new_calib.jsonl"}
    test_paths = {"internal": base / "l4_v5_test.jsonl", "external": base / "l4_v5_external_test.jsonl", "new": out / "new_test.jsonl"}
    tokenizer = AutoTokenizer.from_pretrained(str(models["v6"] / "hf_checkpoint"), local_files_only=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    sessions, report = {}, {"protocol": protocol, "protocol_sha256": digest(out / "protocol.json"), "models": {}, "data_sha256": {str(p.relative_to(root)): digest(p) for p in [*cal_paths.values(), *test_paths.values()]}}
    for name, directory in models.items():
        model_path = directory / "model.onnx"
        model = onnx.load(str(model_path))
        onnx.checker.check_model(model)
        session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        inputs = {i.name: (i.type, i.shape) for i in session.get_inputs()}
        if set(inputs) != {"input_ids", "attention_mask", "token_type_ids"} or any(t != "tensor(int64)" or len(s) != 2 or not all(isinstance(v, str) for v in s) for t, s in inputs.values()):
            raise ValueError(f"invalid input contract: {inputs}")
        if next(v.version for v in model.opset_import if v.domain in ("", "ai.onnx")) != 17:
            raise ValueError("opset must be 17")
        if digest(directory / "vocab.txt") != digest(models["v6"] / "vocab.txt"):
            raise ValueError("vocabulary drift")
        sessions[name] = session
        report["models"][name] = {"model_sha256": digest(model_path), "inputs": inputs, "calibration": {}, "tests": {}}

    def predict(session, texts):
        encoded = tokenizer(texts, padding="max_length", truncation=True, max_length=128, return_tensors="np")
        scores = []
        for i in range(len(texts)):
            feed = {key: value[i:i + 1].astype(np.int64) for key, value in encoded.items() if key in {"input_ids", "attention_mask", "token_type_ids"}}
            logits = session.run(["logits"], feed)[0]
            if logits.shape != (1, 2) or not np.isfinite(logits).all():
                raise ValueError("invalid output contract")
            scores.append(float(logits[0, 1] - logits[0, 0]))
        return np.asarray(scores)

    cal_data = {name: read_rows(path) for name, path in cal_paths.items()}
    for name, session in sessions.items():
        scores = {split: predict(session, texts) for split, (texts, _) in cal_data.items()}
        cut = cutoff(list(scores.values()), [labels for _, labels in cal_data.values()])
        report["models"][name]["cut_logit_margin"] = cut
        for split, values in scores.items():
            report["models"][name]["calibration"][split] = metrics(values, cal_data[split][1], cut)
        print(name, "calibration", report["models"][name]["calibration"], flush=True)
    (out / "calibration_lock.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    for split, path in test_paths.items():
        texts, labels = read_rows(path)
        for name, session in sessions.items():
            scores = predict(session, texts)
            result = metrics(scores, labels, report["models"][name]["cut_logit_margin"])
            report["models"][name]["tests"][split] = result
            np.savez_compressed(out / f"predictions_{name}_{split}.npz", margins=scores, labels=labels)
            print(name, split, result, flush=True)
    for name, session in sessions.items():
        text = "review this banking support request " * 40
        predict(session, [text] * 25)
        latencies = []
        for _ in range(200):
            started = time.perf_counter()
            predict(session, [text])
            latencies.append((time.perf_counter() - started) * 1000)
        report["models"][name]["cpu_tokenize_plus_onnx_ms"] = {"p50": float(np.percentile(latencies, 50)), "p95": float(np.percentile(latencies, 95)), "samples": 200, "threads": 1}
    v6, v8 = report["models"]["v6"], report["models"]["v8"]
    gates = {
        "no_holdout_recall_regression": all(v8["tests"][s]["recall"] >= v6["tests"][s]["recall"] for s in test_paths),
        "all_holdout_fpr_at_most_2pct": all(v8["tests"][s]["fpr"] <= .02 for s in test_paths),
        "higher_mean_holdout_recall": sum(v8["tests"][s]["recall"] for s in test_paths) > sum(v6["tests"][s]["recall"] for s in test_paths),
        "cpu_p95_below_250ms": v8["cpu_tokenize_plus_onnx_ms"]["p95"] < 250,
    }
    report.update(offline_gates=gates, offline_candidate_passed=all(gates.values()), runtime_g1="NOT_MEASURED", promoted=False,
                  limitations=["Wilson intervals assume independent rows; prefix grouping does not prove template/author independence.", "Synthetic longest-window CPU latency is not Java end-to-end latency.", "New source/label correlation limits generalization claims.", "No runtime artifact is replaced by this evaluator."])
    (out / "paired_evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(gates, indent=2), flush=True)


if __name__ == "__main__":
    main()
