"""Benchmark the credit brain (shipped standardized LR) against tree-model rivals.

Reuses credit_brain.featurize (shared train/serve, no skew) and the trainer's split column.
Rivals: HistGradientBoosting, XGBoost, LightGBM. Reports ROC-AUC / PR-AUC on the held-out test
split AND the adaptive-seller holdout, plus single-row latency. SYNTHETIC DATA ONLY: these
numbers show the model recovers the generator's signal, not real-world fraud-detection quality.
No threshold is selected on test; ranking metrics are threshold-free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from credit_brain import FEATURES, featurize  # noqa: E402


def matrix(df: pd.DataFrame) -> np.ndarray:
    return np.array([featurize(r) for r in df.to_dict("records")], dtype=float)


def ranking(y, p) -> dict:
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4),
            "pr_auc": round(float(average_precision_score(y, p)), 4)}


def latency_ms(fn, X: np.ndarray, samples: int = 1000) -> dict:
    n = min(samples, len(X))
    rows = X[np.linspace(0, len(X) - 1, n, dtype=int)]
    for r in rows[:3]:
        fn(r.reshape(1, -1))
    t = []
    for r in rows:
        s = time.perf_counter_ns(); fn(r.reshape(1, -1)); t.append((time.perf_counter_ns() - s) / 1e6)
    return {"p50": round(float(np.percentile(t, 50)), 4), "p95": round(float(np.percentile(t, 95)), 4)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="datasets/synthetic_credit_boost")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--n-jobs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    data = Path(a.data)
    df = pd.read_csv(data / "credit_apps.csv")
    adaptive = pd.read_csv(data / "credit_apps_adaptive.csv")
    tr, va, te = (df[df.split == s].reset_index(drop=True) for s in ("train", "val", "test"))
    Xtr, Xte, Xad = matrix(tr), matrix(te), matrix(adaptive)
    ytr, yte, yad = (d["label"].to_numpy() for d in (tr, te, adaptive))

    scaler = StandardScaler().fit(Xtr)
    scale = np.where(scaler.scale_ > 0, scaler.scale_, 1.0)
    Ztr = (Xtr - scaler.mean_) / scale

    models = {"lr_shipped": LogisticRegression(C=1.0, max_iter=2000).fit(Ztr, ytr),
              "hgb": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08,
                                                    random_state=a.seed).fit(Xtr, ytr)}
    try:
        from xgboost import XGBClassifier
        models["xgboost"] = XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
                                          subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                                          eval_metric="aucpr", n_jobs=a.n_jobs,
                                          random_state=a.seed).fit(Xtr, ytr)
    except ImportError:
        pass
    try:
        from lightgbm import LGBMClassifier
        models["lightgbm"] = LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.05,
                                            subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                            min_child_samples=50, reg_lambda=1.0, n_jobs=a.n_jobs,
                                            random_state=a.seed, verbose=-1).fit(Xtr, ytr)
    except ImportError:
        pass

    results = {}
    for name, m in models.items():
        if name == "lr_shipped":
            pte = m.predict_proba((Xte - scaler.mean_) / scale)[:, 1]
            pad = m.predict_proba((Xad - scaler.mean_) / scale)[:, 1]
            fn = lambda r: m.predict_proba((r - scaler.mean_) / scale)[:, 1]
        else:
            pte, pad = m.predict_proba(Xte)[:, 1], m.predict_proba(Xad)[:, 1]
            fn = lambda r: m.predict_proba(r)[:, 1]
        results[name] = {"test": ranking(yte, pte), "adaptive": ranking(yad, pad),
                         "latency_ms": latency_ms(fn, Xte)}

    report = {
        "caveat": "SYNTHETIC DATA ONLY. Metrics show recovery of the generator's signal, "
                  "not real-world fraud-detection quality. No public real credit-boost/CPN dataset exists.",
        "features": FEATURES,
        "rows": {"train": len(tr), "val": len(va), "test": len(te), "adaptive_holdout": len(adaptive)},
        "positives": {"test": int(yte.sum()), "adaptive": int(yad.sum())},
        "data_sha256": {"credit_apps": hashlib.sha256((data / "credit_apps.csv").read_bytes()).hexdigest(),
                        "adaptive": hashlib.sha256((data / "credit_apps_adaptive.csv").read_bytes()).hexdigest()},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "models": results,
    }
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "credit_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Credit brain benchmark — SYNTHETIC credit-boost data (not real-world quality)", "",
             f"Rows train/val/test/adaptive: {len(tr)}/{len(va)}/{len(te)}/{len(adaptive)}; "
             f"test positives {int(yte.sum())}, adaptive positives {int(yad.sum())}.", "",
             "| Model | test ROC | test PR | adaptive ROC | adaptive PR | p50 ms |",
             "|---|---|---|---|---|---|"]
    for name, m in results.items():
        lines.append(f"| {name} | {m['test']['roc_auc']} | {m['test']['pr_auc']} | "
                     f"{m['adaptive']['roc_auc']} | {m['adaptive']['pr_auc']} | {m['latency_ms']['p50']} |")
    (out / "credit_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()