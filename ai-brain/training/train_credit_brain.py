"""Train the credit brain on the synthetic credit-boost dataset and export it to JSON.

Ships a standardized logistic regression (stdlib inference, readable reason codes).
A HistGradientBoosting model is trained only as a capacity comparison and is not
exported. Thresholds are chosen on the ring-grouped validation split; test and the
adaptive-seller set are scored once with the shipped decision policy end to end.

Metrics on synthetic data show the model recovers the generator's signal, not
real-world fraud-detection quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from credit_brain import FEATURES, CreditBrain, featurize  # noqa: E402

MODEL_VERSION = "credit-brain-lr-v1"
VAL_FPR_TARGET = 0.005
VAL_RECALL_TARGET = 0.95


def adaptive_ring_split(adaptive: pd.DataFrame, train_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deterministic ring-grouped split: a seller ring is entirely train or entirely held-out."""
    def in_train(ring_id: str) -> bool:
        bucket = int(hashlib.sha256(str(ring_id).encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        return bucket < train_fraction

    mask = adaptive["ring_id"].map(in_train)
    return adaptive[mask].reset_index(drop=True), adaptive[~mask].reset_index(drop=True)


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(p, 4), round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def matrix(df: pd.DataFrame) -> np.ndarray:
    return np.array([featurize(r) for r in df.to_dict("records")], dtype=float)


def pick_thresholds(y, p):
    neg, pos = np.sort(p[y == 0]), np.sort(p[y == 1])
    # t_high: smallest cut with FPR <= target; t_low: largest cut keeping recall >= target.
    t_high = float(neg[int(math.ceil(len(neg) * (1 - VAL_FPR_TARGET))) - 1]) + 1e-9
    t_low = float(pos[int(math.floor(len(pos) * (1 - VAL_RECALL_TARGET)))])
    return min(t_low, t_high), t_high


def decision_report(brain: CreditBrain, df: pd.DataFrame) -> dict:
    recs = df.to_dict("records")
    decisions = [brain.assess(r)["decision"] for r in recs]
    df = df.assign(decision=decisions)
    y = df["label"].to_numpy()
    flagged = (df["decision"] != "approve_standard_checks").to_numpy()
    review = (df["decision"] == "manual_review").to_numpy()
    out = {
        "n": int(len(df)), "positives": int(y.sum()),
        "recall_any_action": wilson(int((flagged & (y == 1)).sum()), int((y == 1).sum())),
        "recall_manual_review": wilson(int((review & (y == 1)).sum()), int((y == 1).sum())),
        "fpr_any_action": wilson(int((flagged & (y == 0)).sum()), int((y == 0).sum())),
        "fpr_manual_review": wilson(int((review & (y == 0)).sum()), int((y == 0).sum())),
        "precision_manual_review": wilson(int((review & (y == 1)).sum()), int(review.sum())),
        "by_typology": {},
    }
    for typ, g in df.groupby("typology"):
        n = len(g)
        out["by_typology"][typ] = {
            "n": n,
            "approve": wilson(int((g.decision == "approve_standard_checks").sum()), n),
            "step_up": wilson(int((g.decision == "step_up_verification").sum()), n),
            "manual_review": wilson(int((g.decision == "manual_review").sum()), n),
        }
    return out


def ranking(y, p):
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4),
            "pr_auc": round(float(average_precision_score(y, p)), 4)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="datasets/synthetic_credit_boost")
    ap.add_argument("--out", default="ai-brain/models/credit_brain_v1.json")
    ap.add_argument("--report", default="datasets/synthetic_credit_boost/TRAINING_REPORT.json")
    ap.add_argument("--version", default=MODEL_VERSION)
    ap.add_argument("--adaptive-train-frac", type=float, default=0.0,
                    help="v2: ring-grouped fraction of the adaptive set added to train/val; "
                         "the rest becomes an untouched adaptive holdout")
    ap.add_argument("--compare-model", help="existing model JSON scored on the same splits (v1 vs v2)")
    a = ap.parse_args(argv)
    if not 0.0 <= a.adaptive_train_frac < 1.0:
        ap.error("--adaptive-train-frac must be in [0,1)")

    data = Path(a.data)
    main_csv, adaptive_csv = data / "credit_apps.csv", data / "credit_apps_adaptive.csv"
    df = pd.read_csv(main_csv)
    adaptive = pd.read_csv(adaptive_csv)
    if a.adaptive_train_frac > 0:
        adaptive_train, adaptive = adaptive_ring_split(adaptive, a.adaptive_train_frac)
        # The adaptive CSV has no split column: assign one ring-grouped (80% train / 20% val).
        def train_or_val(ring_id: str) -> str:
            bucket = int(hashlib.sha256(f"split|{ring_id}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
            return "train" if bucket < 0.8 else "val"

        adaptive_train = adaptive_train.assign(split=adaptive_train["ring_id"].map(train_or_val))
        df = pd.concat([df, adaptive_train], ignore_index=True)
    tr, va, te = (df[df.split == s].reset_index(drop=True) for s in ("train", "val", "test"))

    t0 = time.perf_counter()
    Xtr, Xva, Xte, Xad = matrix(tr), matrix(va), matrix(te), matrix(adaptive)
    ytr, yva, yte, yad = (d["label"].to_numpy() for d in (tr, va, te, adaptive))

    scaler = StandardScaler().fit(Xtr)
    scale = np.where(scaler.scale_ > 0, scaler.scale_, 1.0)
    lr = LogisticRegression(C=1.0, max_iter=2000).fit((Xtr - scaler.mean_) / scale, ytr)
    train_s = time.perf_counter() - t0

    def lr_p(X):
        return lr.predict_proba((X - scaler.mean_) / scale)[:, 1]

    t_low, t_high = pick_thresholds(yva, lr_p(Xva))

    hgb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0).fit(Xtr, ytr)

    model = {
        "model_version": a.version,
        "kind": "standardized_logistic_regression",
        "features": FEATURES,
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scale],
        "coef": [float(v) for v in lr.coef_[0]],
        "intercept": float(lr.intercept_[0]),
        "thresholds": {"t_low": t_low, "t_high": t_high,
                       "chosen_on": "val", "val_fpr_target": VAL_FPR_TARGET,
                       "val_recall_target": VAL_RECALL_TARGET},
        "training_data": {
            "credit_apps.csv_sha256": hashlib.sha256(main_csv.read_bytes()).hexdigest(),
            "train_rows": int(len(tr)), "val_rows": int(len(va)), "test_rows": int(len(te)),
            "adaptive_train_frac": a.adaptive_train_frac,
            "adaptive_holdout_rows": int(len(adaptive)),
            "credit_apps_adaptive.csv_sha256": hashlib.sha256(adaptive_csv.read_bytes()).hexdigest(),
        },
        "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                     "numpy": np.__version__},
        "caveat": "Trained on synthetic data only. Metrics show the model recovers the generator's "
                  "signal, not real-world fraud-detection quality.",
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, indent=1), encoding="utf-8")

    brain = CreditBrain.load(out)
    parity = max(abs(brain.score(r)[0] - p) for r, p in zip(te.to_dict("records")[:2000], lr_p(Xte[:2000])))

    rec0 = te.to_dict("records")[0]
    t1 = time.perf_counter()
    for _ in range(2000):
        brain.assess(rec0)
    assess_us = (time.perf_counter() - t1) / 2000 * 1e6

    report = {
        "model_version": a.version,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "processor": platform.processor(), "sklearn": sklearn.__version__},
        "thresholds": model["thresholds"],
        "lr_train_seconds_incl_featurize": round(train_s, 2),
        "json_vs_sklearn_max_abs_prob_diff": float(parity),
        "assess_mean_microseconds_single_thread": round(assess_us, 1),
        "ranking": {
            "lr": {"val": ranking(yva, lr_p(Xva)), "test": ranking(yte, lr_p(Xte)),
                   "adaptive": ranking(yad, lr_p(Xad))},
            "hgb_comparison_not_shipped": {"test": ranking(yte, hgb.predict_proba(Xte)[:, 1]),
                                           "adaptive": ranking(yad, hgb.predict_proba(Xad)[:, 1])},
        },
        "decisions_end_to_end": {"test": decision_report(brain, te),
                                 "adaptive": decision_report(brain, adaptive)},
        "adaptive_split": {
            "train_frac": a.adaptive_train_frac,
            "holdout_rows": int(len(adaptive)),
            "holdout_positives": int(adaptive["label"].sum()),
        },
        "top_coefficients": sorted(({"feature": f, "coef": round(c, 3)} for f, c in zip(FEATURES, lr.coef_[0])),
                                   key=lambda d: -abs(d["coef"]))[:12],
        "caveat": model["caveat"],
        "ci_format": "[point, wilson95_low, wilson95_high]",
    }
    Path(a.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if a.compare_model:
        other = CreditBrain.load(Path(a.compare_model))
        report["comparison_model"] = {
            "model_version": other.version,
            "ranking_adaptive": ranking(yad, np.array([other.score(r)[0] for r in adaptive.to_dict("records")])),
            "ranking_test": ranking(yte, np.array([other.score(r)[0] for r in te.to_dict("records")])),
            "decisions_adaptive": decision_report(other, adaptive),
            "decisions_test": decision_report(other, te),
        }
        Path(a.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
