"""Benchmark the wire-transfer gate (paysim-wire HGB) against XGBoost/LightGBM rivals.

Reuses train_paysim_wire's exact feature engineering, temporal split (by step) and validation-
only threshold discipline so the comparison matches the deployed contract. Reports held-out
TEST ROC-AUC / PR-AUC / recall@FPR / precision / Brier + single-row latency, on all rows and on
the fraud-relevant TRANSFER/CASH_OUT subset. Never downloads data; never selects on test.
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
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score, roc_curve

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_paysim_wire import (FEATURES, classification_metrics, engineer_features,  # noqa: E402
                               fit, load_local_csv, temporal_split)


def robust_threshold(labels, scores, max_fpr):
    fpr, tpr, thr = roc_curve(labels, scores)
    fin = np.isfinite(thr)
    if not fin.any():
        return float(np.max(scores)), False
    ok = (fpr <= max_fpr + 1e-12) & fin
    if not ok.any():
        return float(np.max(thr[fin])), False
    idx = np.flatnonzero(ok)
    idx = idx[tpr[idx] == np.max(tpr[idx])]
    idx = idx[fpr[idx] == np.min(fpr[idx])]
    return float(np.max(thr[idx])), True


def ranking(labels, scores):
    return {"roc_auc": round(float(roc_auc_score(labels, scores)), 5),
            "pr_auc": round(float(average_precision_score(labels, scores)), 5),
            "brier": round(float(brier_score_loss(labels, scores)), 6)}


def latency_ms(fn, X, samples=1000):
    n = min(samples, len(X))
    rows = X[np.linspace(0, len(X) - 1, n, dtype=int)]
    for r in rows[:5]:
        fn(r.reshape(1, -1))
    t = []
    for r in rows:
        s = time.perf_counter_ns(); fn(r.reshape(1, -1)); t.append((time.perf_counter_ns() - s) / 1e6)
    return {"p50": round(float(np.percentile(t, 50)), 4), "p95": round(float(np.percentile(t, 95)), 4),
            "p99": round(float(np.percentile(t, 99)), 4)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-fpr", type=float, default=0.01)
    ap.add_argument("--n-jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--emit-artifact")
    ap.add_argument("--version", default="paysim-wire-v1")
    a = ap.parse_args()

    frame = load_local_csv(a.data)
    tr, va, te = temporal_split(frame)
    Xtr, ytr = tr[FEATURES].to_numpy(np.float64), tr["Class"].to_numpy(int)
    Xva, yva = va[FEATURES].to_numpy(np.float64), va["Class"].to_numpy(int)
    Xte, yte = te[FEATURES].to_numpy(np.float64), te["Class"].to_numpy(int)
    # fraud-relevant subset mask on test (TRANSFER/CASH_OUT)
    sub = (te["is_transfer"].to_numpy() == 1) | (te["is_cash_out"].to_numpy() == 1)
    neg, pos = int((ytr == 0).sum()), max(int(ytr.sum()), 1)
    spw = neg / pos

    models = {"hgb_production": fit(tr, a.seed)}
    try:
        from xgboost import XGBClassifier
        models["xgboost"] = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                                          subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                                          scale_pos_weight=spw, eval_metric="aucpr",
                                          n_jobs=a.n_jobs, random_state=a.seed).fit(Xtr, ytr)
    except ImportError:
        pass
    try:
        from lightgbm import LGBMClassifier
        models["lightgbm"] = LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.05,
                                            subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                            scale_pos_weight=spw, min_child_samples=100, reg_lambda=5.0,
                                            n_jobs=a.n_jobs, random_state=a.seed, verbose=-1).fit(Xtr, ytr)
    except ImportError:
        pass

    results = {}
    for name, m in models.items():
        try:
            t0 = time.perf_counter()
            sva = m.predict_proba(Xva)[:, 1]
            thr, met = robust_threshold(yva, sva, a.max_fpr)
            ste = m.predict_proba(Xte)[:, 1]
            entry = ranking(yte, ste)
            entry.update(classification_metrics(yte, ste, thr))
            entry["fpr_budget_met"] = met
            entry["val_pr_auc"] = round(float(average_precision_score(yva, sva)), 5)
            entry["subset_transfer_cashout"] = ranking(yte[sub], ste[sub]) if sub.any() else None
            entry["latency_ms"] = latency_ms(lambda r: m.predict_proba(r)[:, 1], Xte)
            entry["eval_seconds"] = round(time.perf_counter() - t0, 1)
            results[name] = entry
            if name == "hgb_production" and a.emit_artifact:
                import joblib
                out = Path(a.emit_artifact); out.parent.mkdir(parents=True, exist_ok=True)
                joblib.dump({"model": m, "features": FEATURES, "version": a.version,
                             "threshold": thr, "model_type": "paysim-wire",
                             "validation_max_fpr": a.max_fpr}, out)
        except Exception as exc:
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}

    report = {
        "dataset": "PaySim (local, synthetic mobile-money simulator)",
        "data_sha256": hashlib.sha256(Path(a.data).read_bytes()).hexdigest(),
        "split": "temporal 70/15/15 sorted by step",
        "rows": {"train": len(tr), "validation": len(va), "test": len(te),
                 "test_transfer_cashout": int(sub.sum())},
        "fraud_rate": {"train": round(float(ytr.mean()), 6), "test": round(float(yte.mean()), 6)},
        "features": FEATURES, "validation_fpr_budget": a.max_fpr,
        "threshold_chosen_on": "validation only", "seed": a.seed,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "models": results,
        "note": "PaySim is a synthetic simulator; fraud is concentrated in TRANSFER/CASH_OUT. "
                "Numbers are not real-world wire-fraud quality.",
    }
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "wire_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Wire gate benchmark — PaySim (synthetic, temporal split)", "",
             f"Rows train/val/test: {len(tr)}/{len(va)}/{len(te)}; test fraud {yte.mean():.4%}; "
             f"FPR budget {a.max_fpr} (validation-only threshold).", "",
             "| Model | ROC-AUC | PR-AUC | Recall@FPR | Precision | FPR | subset PR | p50 ms |",
             "|---|---|---|---|---|---|---|---|"]
    for name, m in results.items():
        if "error" in m:
            lines.append(f"| {name} | ERROR {m['error']} | | | | | | |"); continue
        spr = m["subset_transfer_cashout"]["pr_auc"] if m["subset_transfer_cashout"] else "n/a"
        lines.append(f"| {name} | {m['roc_auc']} | {m['pr_auc']} | {m['recall']:.4f} | "
                     f"{m['precision']:.4f} | {m['fpr']:.5f} | {spr} | {m['latency_ms']['p50']} |")
    (out / "wire_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()