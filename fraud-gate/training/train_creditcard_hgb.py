"""Train creditcard-hgb on a caller-supplied local CSV; never downloads data."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_curve

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.card_model import CardModel

FEATURES = [f"V{index}" for index in range(1, 29)] + ["Amount"]
REQUIRED_COLUMNS = ["Time", *FEATURES, "Class"]


def load_local_csv(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"Raw creditcard CSV is required at {source}; no dataset is downloaded or bundled."
        )
    frame = pd.read_csv(source)
    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    if len(frame) < 10:
        raise ValueError("At least 10 rows are required for temporal train/validation/test splits")

    selected = frame[REQUIRED_COLUMNS].copy()
    for name in REQUIRED_COLUMNS:
        selected[name] = pd.to_numeric(selected[name], errors="raise")
    numeric = selected.to_numpy(dtype=np.float64)
    if not np.isfinite(numeric).all():
        raise ValueError("Input contains NaN or infinite values; clean the raw data explicitly")
    if not selected["Class"].isin([0, 1]).all():
        raise ValueError("Class must contain only binary labels 0 and 1")
    selected["Class"] = selected["Class"].astype(np.int64)
    # Sorting before splitting is mandatory: random splitting leaks future patterns.
    return selected.sort_values("Time", kind="stable").reset_index(drop=True)


def temporal_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_end = int(len(frame) * 0.70)
    validation_end = int(len(frame) * 0.85)
    train = frame.iloc[:train_end]
    validation = frame.iloc[train_end:validation_end]
    test = frame.iloc[validation_end:]
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError("Temporal split produced an empty partition")
    if train["Class"].nunique() != 2:
        raise ValueError("Training partition must contain both classes")
    for name, partition in (("validation", validation), ("test", test)):
        if partition["Class"].nunique() != 2:
            raise ValueError(f"{name} partition must contain both classes for FPR/recall evaluation")
    return train, validation, test


def threshold_at_fpr(
    labels: np.ndarray, scores: np.ndarray, max_fpr: float
) -> float:
    """Select on validation data only, maximizing recall within the FPR budget."""
    if not 0 <= max_fpr <= 1:
        raise ValueError("max_fpr must be in [0, 1]")
    fpr, tpr, thresholds = roc_curve(labels, scores)
    eligible = (fpr <= max_fpr + 1e-12) & np.isfinite(thresholds)
    if not eligible.any():
        raise RuntimeError(
            "No finite validation threshold meets the FPR budget; "
            "supply more representative validation data or revise the budget."
        )
    candidates = np.flatnonzero(eligible)
    best_recall = np.max(tpr[candidates])
    candidates = candidates[tpr[candidates] == best_recall]
    best_fpr = np.min(fpr[candidates])
    candidates = candidates[fpr[candidates] == best_fpr]
    return float(np.max(thresholds[candidates]))


def classification_metrics(
    labels: np.ndarray, scores: np.ndarray, threshold: float
) -> dict[str, Any]:
    predicted = scores >= threshold
    positive = labels == 1
    negative = ~positive
    tp = int(np.sum(predicted & positive))
    fp = int(np.sum(predicted & negative))
    fn = int(np.sum(~predicted & positive))
    tn = int(np.sum(~predicted & negative))
    return {
        "threshold": float(threshold),
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "fpr": fp / (fp + tn) if fp + tn else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def gate_latency_ms(
    model: CardModel, test: pd.DataFrame, sample_limit: int = 1000
) -> dict[str, float]:
    """Measure loaded single-request card inference, including named-vector checks."""
    if sample_limit < 1:
        raise ValueError("latency sample limit must be positive")
    count = min(sample_limit, len(test))
    indices = np.linspace(0, len(test) - 1, count, dtype=int)
    rows = [
        {name: float(row[name]) for name in FEATURES}
        for _, row in test.iloc[indices].iterrows()
    ]
    for row in rows[: min(5, len(rows))]:
        model.score(row)
    timings = []
    for row in rows:
        started = time.perf_counter_ns()
        model.score(row)
        timings.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "p50": float(np.percentile(timings, 50)),
        "p95": float(np.percentile(timings, 95)),
        "p99": float(np.percentile(timings, 99)),
        "samples": len(timings),
    }


def fit(train: pd.DataFrame, random_state: int = 42) -> HistGradientBoostingClassifier:
    labels = train["Class"].to_numpy(dtype=int)
    positives = max(int(labels.sum()), 1)
    negatives = max(len(labels) - positives, 1)
    weights = np.where(
        labels == 1,
        len(labels) / (2 * positives),
        len(labels) / (2 * negatives),
    )
    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.08,
        max_leaf_nodes=31,
        min_samples_leaf=100,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=random_state,
    )
    model.fit(train[FEATURES].to_numpy(dtype=np.float64), labels, sample_weight=weights)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Local creditcard.csv; required, never downloaded")
    parser.add_argument("--output", required=True, help="Destination joblib artifact")
    parser.add_argument("--version", required=True, help="Operator-supplied immutable model version")
    parser.add_argument("--max-fpr", type=float, default=0.01, help="Validation false-positive budget")
    parser.add_argument("--latency-samples", type=int, default=1000)
    args = parser.parse_args()

    frame = load_local_csv(args.data)
    train, validation, test = temporal_split(frame)
    model = fit(train)
    validation_scores = model.predict_proba(
        validation[FEATURES].to_numpy(dtype=np.float64)
    )[:, 1]
    threshold = threshold_at_fpr(
        validation["Class"].to_numpy(dtype=int), validation_scores, args.max_fpr
    )
    test_scores = model.predict_proba(test[FEATURES].to_numpy(dtype=np.float64))[:, 1]
    metrics = classification_metrics(test["Class"].to_numpy(dtype=int), test_scores, threshold)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "version": args.version,
            "threshold": threshold,
            "model_type": "creditcard-hgb",
            "validation_max_fpr": args.max_fpr,
        },
        output,
    )
    loaded = CardModel.load(output)
    report = {
        "model_version": args.version,
        "split": "temporal 70%/15%/15% sorted by Time",
        "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "validation_false_positive_budget": args.max_fpr,
        "held_out_test": metrics,
        "gate_latency_ms": gate_latency_ms(loaded, test, args.latency_samples),
        "artifact": str(output),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
