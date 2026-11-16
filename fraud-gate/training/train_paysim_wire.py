"""Train the wire-transfer gate (paysim-wire) on a caller-supplied local PaySim CSV.

Fills the P7/G6 gap: the wire/transfer gate had no trainer, so it could only run as a
rule stub. This mirrors train_creditcard_hgb.py discipline exactly:

  * never downloads data; a local CSV is required;
  * TEMPORAL split by PaySim `step` (random splitting leaks future patterns);
  * threshold chosen on VALIDATION only, maximizing recall within an FPR budget;
  * artifact is a bare HistGradientBoostingClassifier with the SAME keys the strict
    runtime loader (app.card_model.CardModel.load) validates: model/features/version/
    threshold. model_type is "paysim-wire";
  * held-out TEST metrics + single-request gate latency are reported, never assumed.

Feature contract: FEATURES below are numeric and reproducible. engineer_features() maps a
raw PaySim row to that named vector and MUST be used at inference too (the runtime passes
named features straight to the model, so train-time-only transforms would silently break
scoring). The mapping is exported alongside the artifact for the Java wire client.

PaySim columns: step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,
oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud. No real account data is used; names
are dropped and never become features.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_curve

FEATURES = [
    "amount",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
    "balance_delta_orig",
    "balance_delta_dest",
    "error_balance_orig",
    "is_transfer",
    "is_cash_out",
]
RAW_REQUIRED = ["step", "type", "amount", "oldbalanceOrg", "newbalanceOrig",
                "oldbalanceDest", "newbalanceDest", "isFraud"]
MODEL_TYPE = "paysim-wire"


def engineer_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Raw PaySim rows -> the named numeric feature vector (used for train AND inference)."""
    out = pd.DataFrame(index=frame.index)
    amount = pd.to_numeric(frame["amount"], errors="raise")
    old_org = pd.to_numeric(frame["oldbalanceOrg"], errors="raise")
    new_org = pd.to_numeric(frame["newbalanceOrig"], errors="raise")
    old_dest = pd.to_numeric(frame["oldbalanceDest"], errors="raise")
    new_dest = pd.to_numeric(frame["newbalanceDest"], errors="raise")
    kind = frame["type"].astype(str).str.upper()
    out["amount"] = amount
    out["oldbalanceOrg"] = old_org
    out["newbalanceOrig"] = new_org
    out["oldbalanceDest"] = old_dest
    out["newbalanceDest"] = new_dest
    out["balance_delta_orig"] = new_org - old_org
    out["balance_delta_dest"] = new_dest - old_dest
    out["error_balance_orig"] = old_org - amount - new_org
    out["is_transfer"] = (kind == "TRANSFER").astype(np.int64)
    out["is_cash_out"] = (kind == "CASH_OUT").astype(np.int64)
    return out[FEATURES]


def load_local_csv(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Raw PaySim CSV is required at {source}; no dataset is downloaded or bundled.")
    frame = pd.read_csv(source)
    missing = [name for name in RAW_REQUIRED if name not in frame.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    if len(frame) < 10:
        raise ValueError("At least 10 rows are required for temporal train/validation/test splits")
    labels = pd.to_numeric(frame["isFraud"], errors="raise")
    if not labels.isin([0, 1]).all():
        raise ValueError("isFraud must contain only binary labels 0 and 1")
    features = engineer_features(frame)
    numeric = features.to_numpy(dtype=np.float64)
    if not np.isfinite(numeric).all():
        raise ValueError("Engineered features contain NaN or infinite values; clean the raw data explicitly")
    selected = features.copy()
    selected["step"] = pd.to_numeric(frame["step"], errors="raise").to_numpy()
    selected["Class"] = labels.astype(np.int64).to_numpy()
    if not np.isfinite(selected["step"].to_numpy()).all():
        raise ValueError("step contains NaN or infinite values")
    # Sorting before splitting is mandatory: random splitting leaks future patterns.
    return selected.sort_values("step", kind="stable").reset_index(drop=True)


def temporal_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_end = int(len(frame) * 0.70)
    validation_end = int(len(frame) * 0.85)
    train, validation, test = frame.iloc[:train_end], frame.iloc[train_end:validation_end], frame.iloc[validation_end:]
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError("Temporal split produced an empty partition")
    if train["Class"].nunique() != 2:
        raise ValueError("Training partition must contain both classes")
    for name, partition in (("validation", validation), ("test", test)):
        if partition["Class"].nunique() != 2:
            raise ValueError(f"{name} partition must contain both classes for FPR/recall evaluation")
    return train, validation, test


def threshold_at_fpr(labels: np.ndarray, scores: np.ndarray, max_fpr: float) -> float:
    if not 0 <= max_fpr <= 1:
        raise ValueError("max_fpr must be in [0, 1]")
    fpr, tpr, thresholds = roc_curve(labels, scores)
    eligible = (fpr <= max_fpr + 1e-12) & np.isfinite(thresholds)
    if not eligible.any():
        raise RuntimeError("No finite validation threshold meets the FPR budget; supply more representative data.")
    candidates = np.flatnonzero(eligible)
    best_recall = np.max(tpr[candidates])
    candidates = candidates[tpr[candidates] == best_recall]
    best_fpr = np.min(fpr[candidates])
    candidates = candidates[fpr[candidates] == best_fpr]
    return float(np.max(thresholds[candidates]))


def classification_metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
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
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def fit(train: pd.DataFrame, random_state: int = 42) -> HistGradientBoostingClassifier:
    labels = train["Class"].to_numpy(dtype=int)
    positives = max(int(labels.sum()), 1)
    negatives = max(len(labels) - positives, 1)
    weights = np.where(labels == 1, len(labels) / (2 * positives), len(labels) / (2 * negatives))
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.08, max_leaf_nodes=31,
        min_samples_leaf=50, l2_regularization=1.0,
        early_stopping=False, random_state=random_state,
    )
    model.fit(train[FEATURES].to_numpy(dtype=np.float64), labels, sample_weight=weights)
    return model


def gate_latency_ms(model: Any, test: pd.DataFrame, sample_limit: int = 1000) -> dict[str, float]:
    if sample_limit < 1:
        raise ValueError("latency sample limit must be positive")
    count = min(sample_limit, len(test))
    indices = np.linspace(0, len(test) - 1, count, dtype=int)
    rows = [{name: float(row[name]) for name in FEATURES} for _, row in test.iloc[indices].iterrows()]
    for row in rows[: min(5, len(rows))]:
        model.score(row)
    timings = []
    for row in rows:
        started = time.perf_counter_ns()
        model.score(row)
        timings.append((time.perf_counter_ns() - started) / 1_000_000)
    return {"p50": float(np.percentile(timings, 50)), "p95": float(np.percentile(timings, 95)),
            "p99": float(np.percentile(timings, 99)), "samples": len(timings)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Local PaySim CSV; required, never downloaded")
    parser.add_argument("--output", required=True, help="Destination joblib artifact")
    parser.add_argument("--version", required=True, help="Operator-supplied immutable model version")
    parser.add_argument("--max-fpr", type=float, default=0.01, help="Validation false-positive budget")
    parser.add_argument("--latency-samples", type=int, default=1000)
    args = parser.parse_args()

    frame = load_local_csv(args.data)
    train, validation, test = temporal_split(frame)
    model = fit(train)
    validation_scores = model.predict_proba(validation[FEATURES].to_numpy(dtype=np.float64))[:, 1]
    threshold = threshold_at_fpr(validation["Class"].to_numpy(dtype=int), validation_scores, args.max_fpr)
    test_scores = model.predict_proba(test[FEATURES].to_numpy(dtype=np.float64))[:, 1]
    metrics = classification_metrics(test["Class"].to_numpy(dtype=int), test_scores, threshold)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model, "features": FEATURES, "version": args.version, "threshold": threshold,
        "model_type": MODEL_TYPE, "validation_max_fpr": args.max_fpr,
    }, output)

    # Validate against the strict runtime loader (lazy import keeps pure helpers testable).
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.card_model import CardModel
    loaded = CardModel.load(output)

    feature_contract = output.with_name(output.stem + "_features.json")
    feature_contract.write_text(json.dumps({
        "model_type": MODEL_TYPE, "features": FEATURES, "version": args.version,
        "threshold": threshold,
        "mapping": "amount;oldbalanceOrg;newbalanceOrig;oldbalanceDest;newbalanceDest;"
                   "balance_delta_orig=newbalanceOrig-oldbalanceOrg;"
                   "balance_delta_dest=newbalanceDest-oldbalanceDest;"
                   "error_balance_orig=oldbalanceOrg-amount-newbalanceOrig;"
                   "is_transfer=(type==TRANSFER);is_cash_out=(type==CASH_OUT)",
    }, indent=2) + "\n", encoding="utf-8")

    report = {
        "model_version": args.version,
        "model_type": MODEL_TYPE,
        "split": "temporal 70%/15%/15% sorted by step",
        "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "validation_false_positive_budget": args.max_fpr,
        "held_out_test": metrics,
        "gate_latency_ms": gate_latency_ms(loaded, test, args.latency_samples),
        "artifact": str(output),
        "feature_contract": str(feature_contract),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()