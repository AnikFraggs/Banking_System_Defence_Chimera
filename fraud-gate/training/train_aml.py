"""Train + evaluate a transaction-level AML laundering classifier on IBM AMLworld HI-Small.

Synthetic data (IBM AMLworld). NOT proof of real laundering-detection accuracy.
HI-Small is the high-illicit variant but still only ~0.1% positive. Temporal split
by timestamp (70/15/15). Account fan-in/out and amount aggregates are computed on
the TRAIN window only and mapped onto calibration/test (unknown accounts -> 0), so
no future information leaks into training features. Threshold chosen on calibration
only (FPR budget 1%); test scored once. Adopt only if it beats the logistic baseline.

Run: python train_aml.py --authorized-data
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets/IBM_AMLworld/HI-Small_Trans.csv"
DEST = ROOT / "fraud-gate/training/artifacts/aml_laundering"
COLS = ["ts", "from_bank", "from_acct", "to_bank", "to_acct", "amt_recv", "recv_ccy",
        "amt_paid", "pay_ccy", "format", "label"]
FPR_BUDGET = 0.01


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cutoff(scores, labels, budget):
    neg = np.sort(scores[labels == 0])[::-1]
    if len(neg) == 0:
        return float("inf")
    return float(neg[min(int(np.floor(budget * len(neg))), len(neg) - 1)])


def metrics(scores, labels, cut):
    pred = scores > cut
    pos, neg = labels == 1, labels == 0
    tp = int((pred & pos).sum()); fp = int((pred & neg).sum())
    fn = int((~pred & pos).sum()); tn = int((~pred & neg).sum())
    return {"average_precision": float(average_precision_score(labels, scores)),
            "roc_auc": float(roc_auc_score(labels, scores)), "threshold": cut,
            "recall": tp / max(tp + fn, 1), "fpr": fp / max(fp + tn, 1),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": tp / max(tp + fp, 1)}


def recall_at_fpr(scores, labels, target):
    # Comparison-only: threshold matched to a common test FPR. NOT the deployed
    # operating point (that stays calibration-derived).
    cut = cutoff(scores, labels, target)
    pred = scores > cut
    pos = labels == 1
    return float((pred & pos).sum() / max(pos.sum(), 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-data", action="store_true")
    args = parser.parse_args()
    if not args.authorized_data:
        raise SystemExit("--authorized-data required")
    if (DEST / "metadata.json").exists():
        raise SystemExit("metadata.json already exists; refusing to overwrite")
    DEST.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(DATA)
    df.columns = COLS
    df["ts"] = pd.to_datetime(df["ts"], format="%Y/%m/%d %H:%M")
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    n = len(df)
    i_train, i_calib = int(n * 0.70), int(n * 0.85)
    train_m = np.arange(n) < i_train
    calib_m = (np.arange(n) >= i_train) & (np.arange(n) < i_calib)
    test_m = np.arange(n) >= i_calib
    y = df["label"].to_numpy()
    tr = df.iloc[:i_train]

    # Train-only aggregate maps (no future leakage).
    bank_freq = (tr["from_bank"].value_counts() / len(tr)).to_dict()
    out_deg = tr.groupby("from_acct").size().to_dict()
    in_deg = tr.groupby("to_acct").size().to_dict()
    out_amt = tr.groupby("from_acct")["amt_paid"].sum().to_dict()
    in_amt = tr.groupby("to_acct")["amt_recv"].sum().to_dict()
    fan_out = tr.groupby("from_acct")["to_acct"].nunique().to_dict()
    fan_in = tr.groupby("to_acct")["from_acct"].nunique().to_dict()

    feat = pd.DataFrame(index=df.index)
    feat["log_amt_paid"] = np.log1p(df["amt_paid"].clip(lower=0))
    feat["log_amt_recv"] = np.log1p(df["amt_recv"].clip(lower=0))
    feat["amount_ratio"] = df["amt_paid"] / (df["amt_recv"].abs() + 1.0)
    feat["currency_mismatch"] = (df["recv_ccy"] != df["pay_ccy"]).astype(int)
    feat["same_bank"] = (df["from_bank"] == df["to_bank"]).astype(int)
    feat["self_transfer"] = (df["from_acct"] == df["to_acct"]).astype(int)
    feat["hour"] = df["ts"].dt.hour
    feat["dow"] = df["ts"].dt.dayofweek
    feat["from_bank_freq"] = df["from_bank"].map(bank_freq).fillna(0.0)
    feat["to_bank_freq"] = df["to_bank"].map(bank_freq).fillna(0.0)
    feat["from_out_deg"] = df["from_acct"].map(out_deg).fillna(0).astype(float)
    feat["to_in_deg"] = df["to_acct"].map(in_deg).fillna(0).astype(float)
    feat["from_out_amt"] = np.log1p(df["from_acct"].map(out_amt).fillna(0).astype(float))
    feat["to_in_amt"] = np.log1p(df["to_acct"].map(in_amt).fillna(0).astype(float))
    feat["from_fan_out"] = df["from_acct"].map(fan_out).fillna(0).astype(float)
    feat["to_fan_in"] = df["to_acct"].map(fan_in).fillna(0).astype(float)
    for col in ("format", "recv_ccy", "pay_ccy"):
        dummies = pd.get_dummies(df[col], prefix=col).astype(float)
        feat = pd.concat([feat, dummies], axis=1)
    feat = feat.astype(np.float32)
    feature_names = list(feat.columns)
    mat = feat.to_numpy()

    pos = int(y[train_m].sum()); neg = int((y[train_m] == 0).sum())
    spw = neg / max(pos, 1)
    models = {
        "logistic_baseline": Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=13)),
        ]),
        "hgb": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300,
            l2_regularization=1.0, early_stopping=False, random_state=13),
        "xgboost": XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, tree_method="hist", eval_metric="aucpr",
            scale_pos_weight=spw, random_state=13, n_jobs=8),
    }
    results, fitted = {}, {}
    for name, model in models.items():
        model.fit(mat[train_m], y[train_m])
        fitted[name] = model
        cal = model.predict_proba(mat[calib_m])[:, 1]
        cut = cutoff(cal, y[calib_m], FPR_BUDGET)
        test = model.predict_proba(mat[test_m])[:, 1]
        tm = metrics(test, y[test_m], cut)
        tm["recall_at_1pct_fpr_comparison"] = recall_at_fpr(test, y[test_m], FPR_BUDGET)
        results[name] = {"calibration": metrics(cal, y[calib_m], cut), "test": tm}
        print(name, json.dumps(results[name]["test"]), flush=True)

    selected = max(results, key=lambda k: results[k]["calibration"]["average_precision"])
    base, sel = results["logistic_baseline"]["test"], results[selected]["test"]
    # Fair comparison: higher threshold-independent PR-AUC AND more recall at a
    # matched 1% test FPR (comparison-only threshold; deployed cut stays calib-derived).
    beats = (sel["average_precision"] > base["average_precision"]
             and sel["recall_at_1pct_fpr_comparison"] >= base["recall_at_1pct_fpr_comparison"])

    import joblib
    artifact = DEST / "model.joblib"
    joblib.dump({"model": fitted[selected], "feature_names": feature_names, "selected": selected,
                 "aggregate_maps": {"bank_freq": bank_freq, "out_deg": out_deg, "in_deg": in_deg,
                                    "out_amt": out_amt, "in_amt": in_amt,
                                    "fan_out": fan_out, "fan_in": fan_in}}, artifact)

    metadata = {
        "version": "aml-ibm-hi-small-v1",
        "dataset": "datasets/IBM_AMLworld/HI-Small_Trans.csv",
        "dataset_sha256": digest(DATA),
        "synthetic": True,
        "licence_note": "IBM AMLworld is a synthetic research dataset (IBM, CC-BY-NC family); verify upstream licence before redistribution. No local licence file supplied.",
        "variant": "HI-Small (high-illicit variant; prevalence still ~0.1%)",
        "label": "Is Laundering",
        "rows": n, "positives": int(y.sum()), "prevalence": float(y.mean()),
        "time_range": [str(df['ts'].min()), str(df['ts'].max())],
        "split": {"train_frac": 0.70, "calibration_frac": 0.15, "test_frac": 0.15,
                  "train_rows": int(train_m.sum()), "calibration_rows": int(calib_m.sum()),
                  "test_rows": int(test_m.sum()), "train_positives": pos,
                  "calibration_positives": int(y[calib_m].sum()), "test_positives": int(y[test_m].sum())},
        "features": {"count": len(feature_names), "feature_names": feature_names,
                     "leakage_control": "account/bank aggregates computed on train window only; unknown accounts map to 0"},
        "fpr_budget_calibration": FPR_BUDGET,
        "selection": "max calibration average_precision; test scored once",
        "selected_model": selected,
        "beats_logistic_baseline_on_test": bool(beats),
        "results": results,
        "artifact_sha256": digest(artifact),
        "limitations": [
            "synthetic data: not proof of real laundering-detection accuracy",
            "HI-Small enriched-illicit variant; production prevalence is lower",
            "temporal holdout only; account aggregates are train-window snapshots",
            "research only; separate integration required before production use",
        ],
    }
    (DEST / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print("SELECTED", selected, "beats_baseline", beats, flush=True)
    print("artifact", digest(artifact), flush=True)


if __name__ == "__main__":
    main()