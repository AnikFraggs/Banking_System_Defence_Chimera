"""Train + evaluate an account-opening fraud classifier on the Feedzai BAF Base set.

Synthetic data (Feedzai Bank Account Fraud). This is NOT proof of real credit-fraud
accuracy. Temporal split: train months 0-5, calibration month 6, test month 7.
The operating threshold is chosen on calibration only (FPR budget 1%), then the
test month is scored once. Adopt only if it beats the logistic baseline on the
held-out month without a worse false-positive rate.

Run: python train_account_opening.py --authorized-data
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets/feedzai_bank_account_fraud/Base.csv"
DEST = ROOT / "fraud-gate/training/artifacts/account_opening_fraud"

LABEL = "fraud_bool"
TIME = "month"
CATEGORICAL = ["payment_type", "employment_status", "housing_status", "source", "device_os"]
SENTINEL_COLS = ["prev_address_months_count", "current_address_months_count", "credit_risk_score",
                 "bank_months_count", "session_length_in_minutes", "device_distinct_emails_8w"]
FPR_BUDGET = 0.01


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_features(df: pd.DataFrame):
    numeric = [c for c in df.columns if c not in CATEGORICAL + [LABEL, TIME]]
    x = df[numeric].copy()
    for c in SENTINEL_COLS:
        x[c] = x[c].replace(-1, np.nan)
    cats = df[CATEGORICAL].astype("category")
    return x, cats, numeric


def cutoff(scores: np.ndarray, labels: np.ndarray, budget: float) -> float:
    neg = np.sort(scores[labels == 0])[::-1]
    if len(neg) == 0:
        return float("inf")
    index = min(int(np.floor(budget * len(neg))), len(neg) - 1)
    return float(neg[index])


def metrics(scores: np.ndarray, labels: np.ndarray, cut: float):
    pred = scores > cut
    pos, neg = labels == 1, labels == 0
    tp = int((pred & pos).sum()); fp = int((pred & neg).sum())
    fn = int((~pred & pos).sum()); tn = int((~pred & neg).sum())
    return {"average_precision": float(average_precision_score(labels, scores)),
            "roc_auc": float(roc_auc_score(labels, scores)),
            "threshold": cut, "recall": tp / max(tp + fn, 1), "fpr": fp / max(fp + tn, 1),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": tp / max(tp + fp, 1)}


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
    x, cats, numeric = build_features(df)
    y = df[LABEL].to_numpy()
    month = df[TIME].to_numpy()
    train_m = month <= 5
    calib_m = month == 6
    test_m = month == 7

    pre = ColumnTransformer([
        ("num", "passthrough", numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
    ], verbose_feature_names_out=False)
    # HGB/XGB consume NaN natively; the numeric passthrough keeps NaN.
    x_all = pd.concat([x, cats], axis=1)
    pre.fit(x_all.iloc[:1000])
    mat = pre.transform(x_all)
    feature_names = list(pre.get_feature_names_out())

    pos = int(y[train_m].sum()); neg = int((y[train_m] == 0).sum())
    spw = neg / max(pos, 1)
    models = {
        "logistic_baseline": Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=13)),
        ]),
        "hgb": HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=200,
            l2_regularization=1.0, early_stopping=False, random_state=13),
        "xgboost": XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, tree_method="hist", eval_metric="aucpr",
            scale_pos_weight=spw, random_state=13, n_jobs=8),
    }

    results = {}
    fitted = {}
    for name, model in models.items():
        model.fit(mat[train_m], y[train_m])
        fitted[name] = model
        cal = model.predict_proba(mat[calib_m])[:, 1]
        cut = cutoff(cal, y[calib_m], FPR_BUDGET)
        test = model.predict_proba(mat[test_m])[:, 1]
        results[name] = {"calibration": metrics(cal, y[calib_m], cut),
                         "test": metrics(test, y[test_m], cut)}
        print(name, json.dumps(results[name]["test"]), flush=True)

    # Select on calibration PR-AUC only; never on test.
    selected = max(results, key=lambda n: results[n]["calibration"]["average_precision"])
    base = results["logistic_baseline"]["test"]
    sel = results[selected]["test"]
    beats = (sel["average_precision"] > base["average_precision"]
             and sel["fpr"] <= base["fpr"] + 1e-9)

    import joblib
    artifact = DEST / "model.joblib"
    joblib.dump({"model": fitted[selected], "preprocessor": pre,
                 "feature_names": feature_names, "selected": selected}, artifact)

    metadata = {
        "version": "account-opening-feedzai-baf-v1",
        "dataset": "datasets/feedzai_bank_account_fraud/Base.csv",
        "dataset_sha256": digest(DATA),
        "synthetic": True,
        "licence_note": "Feedzai BAF is a synthetic research dataset; verify the upstream licence (CC-BY-NC-ND family) before any redistribution. No local licence file was supplied.",
        "label": LABEL,
        "rows": int(len(df)),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()),
        "split": {"train_months": [0, 5], "calibration_month": 6, "test_month": 7,
                  "train_rows": int(train_m.sum()), "calibration_rows": int(calib_m.sum()),
                  "test_rows": int(test_m.sum())},
        "features": {"numeric": numeric, "categorical": CATEGORICAL,
                     "categorical_levels": {c: sorted(df[c].unique().tolist()) for c in CATEGORICAL},
                     "sentinel_rule": "-1 -> NaN in " + ", ".join(SENTINEL_COLS),
                     "encoded_feature_count": len(feature_names),
                     "feature_names": feature_names},
        "fpr_budget_calibration": FPR_BUDGET,
        "selection": "max calibration average_precision; test scored once",
        "selected_model": selected,
        "beats_logistic_baseline_on_test": bool(beats),
        "results": results,
        "artifact_sha256": digest(artifact),
        "limitations": [
            "synthetic data: not proof of real credit-fraud accuracy",
            "temporal holdout only (month 7); no customer-id group split available",
            "threshold chosen on calibration month 6 at FPR<=1%; test FPR may drift",
            "research only; separate integration required before production use",
        ],
    }
    (DEST / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print("SELECTED", selected, "beats_baseline", beats, flush=True)
    print("artifact", artifact, digest(artifact), flush=True)


if __name__ == "__main__":
    main()