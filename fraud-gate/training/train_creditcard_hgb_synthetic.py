"""Train the established creditcard HGB with validated synthetic hard negatives.

Real-data validation/test partitions remain chronological and contain no synthetic
rows. Synthetic groups are partition-exclusive; held-out synthetic recall is
reported separately and is never presented as real-data performance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.hard_negative_synthesis import (
    FEATURES,
    MAX_RECORDS,
    load_hard_negatives,
)
from training.offline_common import ValidationError
from training.train_creditcard_hgb import (
    classification_metrics,
    fit,
    gate_latency_ms,
    load_local_csv,
    temporal_split,
    threshold_at_fpr,
)
from app.card_model import CardModel

RUNTIME_FEATURES = [*FEATURES, "Amount"]


def synthetic_to_frame(records: Sequence[dict[str, Any]], split: str) -> pd.DataFrame:
    """Project validated records to the runtime contract; log_amount is not a feature."""
    if split not in {"TRAIN", "HELD_OUT"}:
        raise ValueError("split must be TRAIN or HELD_OUT")
    rows = []
    groups: set[str] = set()
    for record in records:
        if record["split"] != split:
            continue
        if record["group_id"] in groups:
            # Multiple events in one group are allowed; this set is for leakage checks.
            pass
        groups.add(record["group_id"])
        rows.append({
            "Time": float(record["Time"]),
            **{name: float(record["card_features"][name]) for name in FEATURES},
            "Amount": float(record["Amount"]),
            "Class": 1,
            "group_id": record["group_id"],
        })
    return pd.DataFrame(rows, columns=["Time", *RUNTIME_FEATURES, "Class", "group_id"])


def assert_group_safe(synthetic_records: Sequence[dict[str, Any]]) -> None:
    partitions: dict[str, set[str]] = {"TRAIN": set(), "HELD_OUT": set()}
    for record in synthetic_records:
        partitions[record["split"]].add(record["group_id"])
    overlap = partitions["TRAIN"] & partitions["HELD_OUT"]
    if overlap:
        raise ValidationError(f"synthetic group leakage detected: {sorted(overlap)[:5]}")


def _metrics_if_applicable(frame: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    labels = frame["Class"].to_numpy(dtype=int)
    if len(frame) == 0:
        return {"rows": 0, "note": "no held-out synthetic rows; no metric claimed"}
    # The generator creates positive hard negatives only. Recall is well-defined;
    # precision/FPR are deliberately not fabricated without negative examples.
    detected = scores >= threshold
    return {
        "rows": len(frame),
        "positive_rows": int(labels.sum()),
        "recall": float(np.mean(detected[labels == 1])) if labels.sum() else None,
        "note": "synthetic positives only; precision and FPR are not applicable",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.authorized_input:
        raise ValidationError("--authorized-input is required for the real creditcard CSV")
    if not 0 <= args.max_fpr <= 1:
        raise ValidationError("max_fpr must be in [0, 1]")
    real = load_local_csv(args.data)
    train_real, validation, test = temporal_split(real)
    synthetic = load_hard_negatives(args.synthetic, max_records=MAX_RECORDS)
    assert_group_safe(synthetic)
    synthetic_train = synthetic_to_frame(synthetic, "TRAIN")
    synthetic_held_out = synthetic_to_frame(synthetic, "HELD_OUT")
    if synthetic_train.empty:
        raise ValidationError("synthetic TRAIN partition is empty")

    # Split real data first. No synthetic timestamp can alter evaluation chronology.
    train = pd.concat(
        [train_real, synthetic_train.drop(columns=["group_id"])], ignore_index=True
    )
    if len(train) < 2 or train["Class"].nunique() != 2:
        raise ValidationError("combined training partition must contain both classes")
    model = fit(train, random_state=args.seed)
    validation_scores = model.predict_proba(
        validation[RUNTIME_FEATURES].to_numpy(dtype=np.float64)
    )[:, 1]
    threshold = threshold_at_fpr(
        validation["Class"].to_numpy(dtype=int), validation_scores, args.max_fpr
    )
    test_scores = model.predict_proba(test[RUNTIME_FEATURES].to_numpy(dtype=np.float64))[:, 1]
    real_metrics = classification_metrics(
        test["Class"].to_numpy(dtype=int), test_scores, threshold
    )
    if len(synthetic_held_out):
        synthetic_scores = model.predict_proba(
            synthetic_held_out[RUNTIME_FEATURES].to_numpy(dtype=np.float64)
        )[:, 1]
    else:
        synthetic_scores = np.asarray([], dtype=np.float64)
    synthetic_metrics = _metrics_if_applicable(synthetic_held_out, synthetic_scores, threshold)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": RUNTIME_FEATURES,
            "version": args.version,
            "threshold": threshold,
            "model_type": "creditcard-hgb",
            "validation_max_fpr": args.max_fpr,
            "synthetic_training": {
                "schema": "chimera.hard_negative.v1",
                "train_rows": len(synthetic_train),
                "held_out_rows": len(synthetic_held_out),
                "seed": args.seed,
            },
        },
        output,
    )
    loaded = CardModel.load(output)
    return {
        "model_version": args.version,
        "features": RUNTIME_FEATURES,
        "log_amount_used": False,
        "split": "real temporal 70%/15%/15%; synthetic train-only augmentation; group-disjoint synthetic holdout",
        "rows": {
            "real_train": len(train_real),
            "synthetic_train": len(synthetic_train),
            "combined_train": len(train),
            "real_validation": len(validation),
            "real_test": len(test),
            "synthetic_held_out": len(synthetic_held_out),
        },
        "validation_false_positive_budget": args.max_fpr,
        "real_held_out_test": real_metrics,
        "synthetic_held_out": synthetic_metrics,
        "gate_latency_ms": gate_latency_ms(loaded, test, args.latency_samples),
        "artifact": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Authorized local creditcard.csv")
    parser.add_argument("--authorized-input", action="store_true", required=True)
    parser.add_argument("--synthetic", required=True, help="Validated hard-negative JSONL")
    parser.add_argument("--output", required=True, help="Destination joblib artifact")
    parser.add_argument("--version", required=True, help="Operator-supplied immutable model version")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-fpr", type=float, default=0.01)
    parser.add_argument("--latency-samples", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
