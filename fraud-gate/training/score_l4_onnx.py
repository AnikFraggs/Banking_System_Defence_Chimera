"""Score an exported L4 semantic ONNX model on a labeled JSONL set (semantic model only).

Rows: {"id"?, "text"|"payload", "label": 0|1, "source"?}. Used for dev hard-negative
mining, threshold calibration and external-set comparison. The end-to-end L4 number
(deterministic rules + semantic guard) still comes from the Java L4RealDataEvaluation.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from pathlib import Path


def load_rows(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            text = record.get("text", record.get("payload"))
            if not isinstance(text, str) or record.get("label") not in (0, 1):
                raise ValueError(f"line {number}: needs text/payload and label 0|1")
            rows.append({
                "id": str(record.get("id", number)),
                "text": text,
                "label": record["label"],
                "source": str(record.get("source", "all")),
            })
    if not rows:
        raise ValueError("no rows")
    return rows


def wilson(successes: int, total: int, z: float = 1.959964) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def confusion(labels: list[int], probs: list[float], threshold: float) -> dict:
    tp = fp = tn = fn = 0
    for label, prob in zip(labels, probs):
        hit = prob >= threshold
        if label == 1 and hit:
            tp += 1
        elif label == 1:
            fn += 1
        elif hit:
            fp += 1
        else:
            tn += 1
    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "recall_ci95": wilson(tp, tp + fn),
        "fpr": round(fp / (fp + tn), 4) if fp + tn else None,
        "fpr_ci95": wilson(fp, fp + tn),
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
    }


def choose_threshold(labels: list[int], probs: list[float], max_fpr: float) -> float:
    """Lowest threshold whose FPR on this set stays <= max_fpr (pick on a calibration split only)."""
    benign = sorted((p for p, y in zip(probs, labels) if y == 0), reverse=True)
    if not benign:
        raise ValueError("calibration needs benign rows")
    allowed = math.floor(max_fpr * len(benign))
    if allowed >= len(benign):
        return 0.0
    return min(1.0, math.nextafter(benign[allowed], 2.0))


class OnnxScorer:
    def __init__(self, model: str | Path, tokenizer_dir: str | Path, max_length: int = 128) -> None:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        self.tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir))
        self.max_length = max_length
        self.inputs = {item.name for item in self.session.get_inputs()}

    def predict(self, texts: list[str], batch_size: int = 32) -> list[float]:
        import numpy as np

        probs: list[float] = []
        for start in range(0, len(texts), batch_size):
            encoded = self.tokenizer(
                texts[start:start + batch_size], truncation=True, max_length=self.max_length,
                padding="max_length", return_tensors="np",
            )
            feed = {name: encoded[name].astype(np.int64) for name in self.inputs}
            logits = self.session.run(None, feed)[0].astype(np.float64)
            shifted = logits - logits.max(axis=1, keepdims=True)
            exp = np.exp(shifted)
            probs.extend((exp[:, 1] / exp.sum(axis=1)).tolist())
        return probs


def report(rows: list[dict], probs: list[float], threshold: float) -> dict:
    by_source: dict[str, tuple[list[int], list[float]]] = defaultdict(lambda: ([], []))
    for row, prob in zip(rows, probs):
        by_source[row["source"]][0].append(row["label"])
        by_source[row["source"]][1].append(prob)
    labels = [row["label"] for row in rows]
    return {
        "rows": len(rows),
        "threshold": threshold,
        "overall": confusion(labels, probs, threshold),
        "by_source": {key: confusion(y, p, threshold) for key, (y, p) in sorted(by_source.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", required=True, help="model.int8.onnx")
    parser.add_argument("--tokenizer", required=True, help="encoder/ dir with tokenizer.json")
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--calibrate-max-fpr", type=float,
                        help="choose a threshold for the requested false-positive budget")
    parser.add_argument("--calibration-data",
                        help="separate labeled calibration JSONL; required with --calibrate-max-fpr for held-out scoring")
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--out-json")
    parser.add_argument("--out-probs", help="CSV id,label,source,prob")
    args = parser.parse_args()

    rows = load_rows(args.data)
    scorer = OnnxScorer(args.model, args.tokenizer, args.max_length)
    started = time.perf_counter()
    probs = scorer.predict([row["text"] for row in rows])
    elapsed = time.perf_counter() - started
    threshold = args.threshold
    if args.calibrate_max_fpr is not None:
        if args.calibration_data:
            calibration_rows = load_rows(args.calibration_data)
            calibration_probs = scorer.predict([row["text"] for row in calibration_rows])
            threshold = choose_threshold([row["label"] for row in calibration_rows],
                                         calibration_probs, args.calibrate_max_fpr)
        else:
            # Backwards-compatible calibration-only use. For final reporting, pass
            # --calibration-data so the scored set stays completely held out.
            threshold = choose_threshold([row["label"] for row in rows], probs, args.calibrate_max_fpr)
    result = report(rows, probs, threshold)
    result.update({
        "data": str(args.data),
        "model": str(args.model),
        "calibrated_for_max_fpr": args.calibrate_max_fpr,
        "calibration_data": args.calibration_data,
        "batch_ms_per_row": round(1000 * elapsed / len(rows), 3),
    })
    if args.out_probs:
        with open(args.out_probs, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "label", "source", "prob"])
            for row, prob in zip(rows, probs):
                writer.writerow([row["id"], row["label"], row["source"], f"{prob:.6f}"])
    text = json.dumps(result, indent=2)
    if args.out_json:
        Path(args.out_json).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
