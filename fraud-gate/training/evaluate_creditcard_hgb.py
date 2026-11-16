"""Evaluate an existing artifact on the temporal held-out slice of a local CSV."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.card_model import CardModel
from training.train_creditcard_hgb import (
    FEATURES,
    classification_metrics,
    gate_latency_ms,
    load_local_csv,
    temporal_split,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Local creditcard.csv; required, never downloaded")
    parser.add_argument("--artifact", required=True, help="Existing creditcard-hgb joblib artifact")
    parser.add_argument("--max-fpr", type=float, default=0.01, help="Budget used to assess held-out FPR")
    parser.add_argument("--latency-samples", type=int, default=1000)
    args = parser.parse_args()
    if not 0 <= args.max_fpr <= 1:
        parser.error("--max-fpr must be in [0, 1]")

    frame = load_local_csv(args.data)
    _train, _validation, test = temporal_split(frame)
    loaded = CardModel.load(args.artifact)
    if tuple(FEATURES) != loaded.features:
        raise ValueError(
            f"Artifact feature order {loaded.features!r} does not match required order {tuple(FEATURES)!r}"
        )
    matrix = test[FEATURES].to_numpy(dtype=np.float64)
    scores = loaded.model.predict_proba(matrix)[:, 1]
    metrics = classification_metrics(
        test["Class"].to_numpy(dtype=int), scores, loaded.threshold
    )
    report = {
        "model_version": loaded.version,
        "split": "temporal held-out last 15%, sorted by Time",
        "rows": len(test),
        "false_positive_budget": args.max_fpr,
        "within_fpr_budget": metrics["fpr"] <= args.max_fpr,
        "held_out_test": metrics,
        "gate_latency_ms": gate_latency_ms(loaded, test, args.latency_samples),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
