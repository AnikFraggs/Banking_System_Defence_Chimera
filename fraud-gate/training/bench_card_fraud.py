"""Benchmark the card-fraud gate against strong open-source rivals on IDENTICAL splits.

Trains the production HistGradientBoostingClassifier (the bare-HGB contract card_model.py
accepts) plus XGBoost and LightGBM rivals on the same chronological 70/15/15 split of the
local ULB creditcard.csv, chooses each threshold on VALIDATION only at a fixed FPR budget,
and reports held-out TEST ROC-AUC / PR-AUC / recall@FPR / Brier / single-row latency.

Never downloads data. Never selects on test. Emits a JSON + Markdown comparison with full
provenance (data sha256, row counts, fraud rate, library versions, seed). Literature SOTA is
cited separately in the report, never mixed with reproduced numbers.

Optionally emits the production HGB artifact under the strict runtime contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score, roc_curve)

FEATURES = [f"V{i}" for i in range(1, 29)] + ["Amount"]
REQUIRED = ["Time", *FEATURES, "Class"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_ulb(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"local ULB creditcard.csv required at {path}; never downloaded")
    frame = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    frame = frame[REQUIRED].copy()
    for c in REQUIRED:
        frame[c] = pd.to_numeric(frame[c], errors="raise")
    if not np.isfinite(frame.to_numpy(dtype=np.float64)).all():
        raise ValueError("non-finite values in input")
    if not frame["Class"].isin([0, 1]).all():
        raise ValueError("Class must be binary")
    frame["Class"] = frame["Class"].astype(np.int64)
    return frame.sort_values("Time", kind="stable").reset_index(drop=True)


def temporal_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    a, b = int(len(frame) * 0.70), int(len(frame) * 0.85)
    tr, va, te = frame.iloc[:a], frame.iloc[a:b], frame.iloc[b:]
    for name, part in (("train", tr), ("validation", va), ("test", te)):
        if part["Class"].nunique() != 2:
            raise ValueError(f"{name} partition must contain both classes")
    return tr, va, te


def threshold_at_fpr(labels: np.ndarray, scores: np.ndarray, max_fpr: float) -> tuple[float, bool]:
    """Most conservative validation threshold meeting the FPR budget.

    Returns (threshold, budget_met). If scores are too coarse to meet the budget at any
    finite threshold, fall back to the highest finite threshold and flag budget_met=False
    rather than crashing the whole comparison.
    """
    fpr, tpr, thr = roc_curve(labels, scores)
    finite = np.isfinite(thr)
    if not finite.any():
        return float(np.max(scores)), False
    ok = (fpr <= max_fpr + 1e-12) & finite
    if not ok.any():
        return float(np.max(thr[finite])), False
    idx = np.flatnonzero(ok)
    idx = idx[tpr[idx] == np.max(tpr[idx])]
    idx = idx[fpr[idx] == np.min(fpr[idx])]
    return float(np.max(thr[idx])), True


def test_metrics(labels: np.ndarray, scores: np.ndarray, thr: float) -> dict[str, Any]:
    pred = scores >= thr
    pos = labels == 1
    tp = int(np.sum(pred & pos)); fp = int(np.sum(pred & ~pos))
    fn = int(np.sum(~pred & pos)); tn = int(np.sum(~pred & ~pos))
    return {
        "roc_auc": round(float(roc_auc_score(labels, scores)), 5),
        "pr_auc": round(float(average_precision_score(labels, scores)), 5),
        "brier": round(float(brier_score_loss(labels, scores)), 6),
        "threshold": round(float(thr), 6),
        "recall": round(tp / (tp + fn), 5) if tp + fn else 0.0,
        "precision": round(tp / (tp + fp), 5) if tp + fp else 0.0,
        "fpr": round(fp / (fp + tn), 6) if fp + tn else 0.0,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def latency_ms(predict_fn, X: np.ndarray, samples: int = 1000) -> dict[str, float]:
    n = min(samples, len(X))
    idx = np.linspace(0, len(X) - 1, n, dtype=int)
    rows = X[idx]
    for r in rows[:5]:
        predict_fn(r.reshape(1, -1))
    t = []
    for r in rows:
        s = time.perf_counter_ns()
        predict_fn(r.reshape(1, -1))
        t.append((time.perf_counter_ns() - s) / 1e6)
    return {"p50": round(float(np.percentile(t, 50)), 4),
            "p95": round(float(np.percentile(t, 95)), 4),
            "p99": round(float(np.percentile(t, 99)), 4), "samples": n}


def build_models(neg: int, pos: int, seed: int, n_jobs: int) -> dict[str, Any]:
    spw = neg / max(pos, 1)
    models: dict[str, Any] = {
        "hgb_production": HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=100,
            l2_regularization=1.0, early_stopping=False, random_state=seed),
    }
    try:
        from xgboost import XGBClassifier
        models["xgboost"] = XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, tree_method="hist", scale_pos_weight=spw,
            eval_metric="aucpr", n_jobs=n_jobs, random_state=seed)
    except ImportError:
        pass
    try:
        from lightgbm import LGBMClassifier
        models["lightgbm"] = LGBMClassifier(
            n_estimators=200, num_leaves=31, learning_rate=0.05, subsample=0.8,
            subsample_freq=1, colsample_bytree=0.8, scale_pos_weight=spw,
            min_child_samples=100, reg_lambda=5.0, n_jobs=n_jobs,
            random_state=seed, verbose=-1)
    except ImportError:
        pass
    return models


def fit_model(name: str, model: Any, X: np.ndarray, y: np.ndarray) -> Any:
    if name == "hgb_production":
        pos = max(int(y.sum()), 1); neg = max(len(y) - pos, 1)
        w = np.where(y == 1, len(y) / (2 * pos), len(y) / (2 * neg))
        model.fit(X, y, sample_weight=w)
    else:
        model.fit(X, y)
    return model


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", required=True, help="local ULB creditcard.csv")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--max-fpr", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-jobs", type=int, default=4)
    p.add_argument("--latency-samples", type=int, default=1000)
    p.add_argument("--emit-artifact", help="also write the production HGB joblib here")
    p.add_argument("--version", default="creditcard-hgb-ulb-v1")
    args = p.parse_args()

    data = Path(args.data)
    frame = load_ulb(data)
    tr, va, te = temporal_split(frame)
    Xtr, ytr = tr[FEATURES].to_numpy(np.float64), tr["Class"].to_numpy(int)
    Xva, yva = va[FEATURES].to_numpy(np.float64), va["Class"].to_numpy(int)
    Xte, yte = te[FEATURES].to_numpy(np.float64), te["Class"].to_numpy(int)
    neg, pos = int((ytr == 0).sum()), int((ytr == 1).sum())

    import sklearn
    results: dict[str, Any] = {}
    versions = {"sklearn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__}
    for name, model in build_models(neg, pos, args.seed, args.n_jobs).items():
        try:
            t0 = time.perf_counter()
            model = fit_model(name, model, Xtr, ytr)
            train_s = time.perf_counter() - t0
            va_scores = model.predict_proba(Xva)[:, 1]
            thr, met = threshold_at_fpr(yva, va_scores, args.max_fpr)
            te_scores = model.predict_proba(Xte)[:, 1]
            m = test_metrics(yte, te_scores, thr)
            m["fpr_budget_met"] = met
            m["val_pr_auc"] = round(float(average_precision_score(yva, va_scores)), 5)
            m["train_seconds"] = round(train_s, 2)
            m["latency_ms"] = latency_ms(lambda r: model.predict_proba(r)[:, 1], Xte, args.latency_samples)
            results[name] = m
            if name == "hgb_production" and args.emit_artifact:
                out = Path(args.emit_artifact); out.parent.mkdir(parents=True, exist_ok=True)
                joblib.dump({"model": model, "features": FEATURES, "version": args.version,
                             "threshold": thr, "model_type": "creditcard-hgb",
                             "validation_max_fpr": args.max_fpr}, out)
            versions[name] = type(model).__module__.split(".")[0]
        except Exception as exc:  # isolate one rival's failure; keep the comparison honest
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}

    report = {
        "dataset": "ULB creditcard.csv (Kaggle, real)",
        "data_sha256": sha256_file(data),
        "split": "temporal 70/15/15 sorted by Time",
        "rows": {"train": len(tr), "validation": len(va), "test": len(te)},
        "fraud_rate": {"train": round(float(ytr.mean()), 6), "test": round(float(yte.mean()), 6)},
        "features": FEATURES,
        "validation_fpr_budget": args.max_fpr,
        "threshold_chosen_on": "validation only",
        "seed": args.seed,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "versions": versions},
        "models": results,
        "literature_reference_not_reproduced": {
            "note": "Published ULB results vary by split/metric; compare PR-AUC and recall@FPR, not accuracy.",
            "typical_strong_tree_pr_auc": "0.80-0.90 on random splits; temporal splits are harder",
        },
    }
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "card_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = ["# Card fraud benchmark — ULB creditcard.csv (real, temporal split)", "",
             f"Rows train/val/test: {len(tr)}/{len(va)}/{len(te)}; test fraud rate {yte.mean():.4%}; "
             f"FPR budget {args.max_fpr} (threshold chosen on validation only).", "",
             "| Model | ROC-AUC | PR-AUC | Recall@FPR | Precision | FPR | Brier | train s | p50 ms | p95 ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in results.items():
        if "error" in m:
            lines.append(f"| {name} | ERROR: {m['error']} | | | | | | | | |")
            continue
        lines.append(f"| {name} | {m['roc_auc']} | {m['pr_auc']} | {m['recall']} | {m['precision']} | "
                     f"{m['fpr']} | {m['brier']} | {m['train_seconds']} | {m['latency_ms']['p50']} | "
                     f"{m['latency_ms']['p95']} |")
    (out_dir / "card_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()