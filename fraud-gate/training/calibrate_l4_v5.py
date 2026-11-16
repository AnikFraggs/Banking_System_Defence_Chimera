"""Freeze ONE L4 deployment threshold under distribution shift, then report honestly.

Why this exists
---------------
score_l4_onnx.choose_threshold() picks a threshold on a SINGLE calibration set. v4
calibrated on the in-domain dev slice only, then reported SPML-native recall 16.7% at
FPR 9.9%: the in-domain-optimal threshold does not transfer to persona-style attacks.

This tool selects a single threshold that satisfies a worst-case false-positive budget
across BOTH locked calibration slices (in-domain calib + external/SPML calib) and never
looks at either TEST slice while choosing. It then reports held-out TEST metrics at the
frozen threshold with Wilson 95% CIs, and writes a small deployment sidecar
(``l4_v5_threshold.json``) that the Java guard / compose L4_SEMANTIC_THRESHOLD can read.

Two selection methods:
  * worst_case_fpr (default): per-slice empirical threshold at the FPR budget, then the
    MAX across slices (the least-conservative threshold that keeps EVERY slice <= budget,
    i.e. maximizes recall subject to worst-case FPR).
  * conformal: split-conformal upper quantile of benign calibration scores with the
    finite-sample (n+1) correction, giving distribution-free FPR <= alpha in expectation
    over calibration draws. More conservative; use when the external slice is small.

This script only scores an existing artifact and chooses a threshold. It never trains,
never downloads, and never selects on a test slice.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

try:
    from .score_l4_onnx import OnnxScorer, choose_threshold, confusion, load_rows, wilson
except ImportError:  # executed as a flat script
    from score_l4_onnx import OnnxScorer, choose_threshold, confusion, load_rows, wilson


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def worst_case_threshold(slices: list[tuple[list[int], list[float]]], max_fpr: float) -> float:
    """MAX of per-slice empirical thresholds: keeps every slice's FPR <= max_fpr.

    A higher threshold can only lower FPR, so the max of the per-slice minima is the
    least-conservative threshold that satisfies all slices simultaneously.
    """
    if not slices:
        raise ValueError("at least one calibration slice is required")
    if not 0.0 <= max_fpr <= 1.0:
        raise ValueError("max_fpr must be in [0, 1]")
    return max(choose_threshold(labels, probs, max_fpr) for labels, probs in slices)


def conformal_threshold(slices: list[tuple[list[int], list[float]]], alpha: float) -> float:
    """Split-conformal FPR control pooled over all calibration benign scores.

    threshold = the ceil((1-alpha)*(n+1))-th smallest benign score (finite-sample
    correction). If the calibration set is too small to certify alpha, fail closed to a
    threshold above 1.0 so nothing is auto-passed on the strength of this calibration.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    benign = sorted(p for labels, probs in slices for p, y in zip(probs, labels) if y == 0)
    n = len(benign)
    if n == 0:
        raise ValueError("conformal calibration needs benign rows")
    rank = math.ceil((1.0 - alpha) * (n + 1))
    if rank > n:
        return math.nextafter(1.0, 2.0)  # cannot certify alpha -> fail closed
    return min(1.0, math.nextafter(benign[rank - 1], 2.0))


def realized_fpr(labels: list[int], probs: list[float], threshold: float) -> float | None:
    benign = [p for p, y in zip(probs, labels) if y == 0]
    if not benign:
        return None
    return sum(1 for p in benign if p >= threshold) / len(benign)


def _slice_metrics(rows: list[dict], probs: list[float], threshold: float) -> dict:
    labels = [row["label"] for row in rows]
    overall = confusion(labels, probs, threshold)
    by_source: dict[str, tuple[list[int], list[float]]] = {}
    for row, prob in zip(rows, probs):
        bucket = by_source.setdefault(row["source"], ([], []))
        bucket[0].append(row["label"])
        bucket[1].append(prob)
    return {
        "rows": len(rows),
        "overall": overall,
        "by_source": {key: confusion(y, p, threshold) for key, (y, p) in sorted(by_source.items())},
    }


def select(args: argparse.Namespace) -> dict:
    scorer = OnnxScorer(args.model, args.tokenizer, args.max_length)

    calib_paths = {"in_domain_calib": args.in_domain_calib}
    if args.external_calib:
        calib_paths["external_calib"] = args.external_calib
    calib_rows = {name: load_rows(path) for name, path in calib_paths.items()}
    calib_probs = {name: scorer.predict([r["text"] for r in rows]) for name, rows in calib_rows.items()}
    slices = [( [r["label"] for r in calib_rows[name]], calib_probs[name]) for name in calib_rows]

    if args.method == "conformal":
        threshold = conformal_threshold(slices, args.alpha)
    else:
        threshold = worst_case_threshold(slices, args.max_fpr)

    # The chosen threshold must respect the empirical budget on every calibration slice.
    calib_report = {}
    worst_calib_fpr = 0.0
    for name in calib_rows:
        labels = [r["label"] for r in calib_rows[name]]
        fpr = realized_fpr(labels, calib_probs[name], threshold)
        calib_report[name] = {
            "rows": len(calib_rows[name]),
            "fpr_at_threshold": round(fpr, 6) if fpr is not None else None,
            "metrics": _slice_metrics(calib_rows[name], calib_probs[name], threshold),
        }
        if fpr is not None:
            worst_calib_fpr = max(worst_calib_fpr, fpr)
    if args.method == "worst_case_fpr" and worst_calib_fpr > args.max_fpr + 1e-9:
        raise SystemExit(
            f"selected threshold violates the FPR budget on a calibration slice: "
            f"{worst_calib_fpr} > {args.max_fpr}"
        )

    # TEST slices are scored only AFTER the threshold is frozen; they never influence it.
    test_paths = {"in_domain_test": args.in_domain_test}
    if args.external_test:
        test_paths["external_test"] = args.external_test
    test_report = {}
    for name, path in test_paths.items():
        rows = load_rows(path)
        probs = scorer.predict([r["text"] for r in rows])
        test_report[name] = _slice_metrics(rows, probs, threshold)

    manifest = {
        "version": args.version,
        "method": args.method,
        "max_fpr_budget": args.max_fpr if args.method == "worst_case_fpr" else None,
        "conformal_alpha": args.alpha if args.method == "conformal" else None,
        "threshold": round(threshold, 6),
        "threshold_selected_on": sorted(calib_rows),
        "threshold_never_selected_on_test": True,
        "worst_case_calib_fpr": round(worst_calib_fpr, 6),
        "max_length": args.max_length,
        "calibration": calib_report,
        "held_out_test": test_report,
        "provenance": {
            "model": str(args.model),
            "model_sha256": sha256_file(args.model),
            "calib_sha256": {name: sha256_file(path) for name, path in calib_paths.items()},
            "test_sha256": {name: sha256_file(path) for name, path in test_paths.items()},
        },
    }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="model.int8.onnx")
    parser.add_argument("--tokenizer", required=True, help="encoder/ dir with tokenizer.json")
    parser.add_argument("--in-domain-calib", required=True)
    parser.add_argument("--external-calib", help="locked external/SPML calibration slice")
    parser.add_argument("--in-domain-test", required=True)
    parser.add_argument("--external-test", help="honest external generalization slice")
    parser.add_argument("--max-fpr", type=float, default=0.02, help="worst-case FPR budget")
    parser.add_argument("--method", choices=["worst_case_fpr", "conformal"], default="worst_case_fpr")
    parser.add_argument("--alpha", type=float, default=0.02, help="conformal miscoverage / FPR target")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--version", default="l4-v5-calibration")
    parser.add_argument("--out-json", required=True, help="full calibration + held-out report")
    parser.add_argument("--out-threshold", help="deployment sidecar {threshold,...}; default beside out-json")
    args = parser.parse_args()
    if not 0.0 <= args.max_fpr <= 1.0:
        parser.error("--max-fpr must be in [0, 1]")
    if not 0.0 < args.alpha < 1.0:
        parser.error("--alpha must be in (0, 1)")

    manifest = select(args)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    sidecar = Path(args.out_threshold) if args.out_threshold else out_json.with_name("l4_v5_threshold.json")
    sidecar.write_text(json.dumps({
        "threshold": manifest["threshold"],
        "method": manifest["method"],
        "max_fpr": manifest["max_fpr_budget"],
        "alpha": manifest["conformal_alpha"],
        "model_sha256": manifest["provenance"]["model_sha256"],
        "version": manifest["version"],
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()