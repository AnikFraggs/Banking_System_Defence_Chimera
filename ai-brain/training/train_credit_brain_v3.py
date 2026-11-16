"""Credit brain v3 candidate: LightGBM trees served by stdlib traversal, reason codes from tree paths.

Uses the EXACT v2 splits (verified against credit_brain_v2.json), picks thresholds on val with the
v2 rule, then scores v2 and v3 end to end (CreditBrain.assess, hard red flags included) on:
  * test, the ring-grouped adaptive holdout (as in v2), and
  * a NEW stress set: fresh adaptive seller rings from an unseen generator seed, plus a
    "stealth" copy where each fraud row grafts attacker-controllable fields (contact ages,
    address match, device fan-out, document quality, inquiries) from random legit rows.
    Bureau-side facts (file age, tradelines, eCBSV, identity links) are left untouched because
    an applicant cannot rewrite them.
Adopted as the serving default only because it beat v2 here (see benchmarks/credit_v3); v2 stays for rollback.
SYNTHETIC DATA ONLY.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from bench_credit_onnx import v2_splits  # noqa: E402
from credit_brain import FEATURES, CreditBrain  # noqa: E402
from generate_credit_apps import generate  # noqa: E402
from train_credit_brain import decision_report, matrix, pick_thresholds, ranking  # noqa: E402

CONTROLLABLE = ["phone_age_days", "email_age_days", "address_matches_bureau", "device_identities_30d",
                "doc_tamper_score", "inquiries_6m"]


def flatten(tree: dict) -> dict:
    f, t, l, r, v = [], [], [], [], []

    def walk(node) -> int:
        i = len(f)
        f.append(-1); t.append(0.0); l.append(-1); r.append(-1); v.append(0.0)
        if "leaf_value" in node:
            v[i] = float(node["leaf_value"])
            return i
        if node.get("decision_type", "<=") != "<=":
            raise SystemExit(f"unsupported split {node.get('decision_type')}")
        f[i] = int(node["split_feature"]); t[i] = float(node["threshold"]); v[i] = float(node["internal_value"])
        l[i] = walk(node["left_child"]); r[i] = walk(node["right_child"])
        return i

    walk(tree["tree_structure"])
    return {"f": f, "t": t, "l": l, "r": r, "v": v}


def stress_sets(seed: int, rows: int, fraud_rate: float):
    fresh = pd.DataFrame(generate(rows, fraud_rate, seed, adaptive=True))
    rng = np.random.default_rng(seed + 1)
    legit = fresh[fresh.label == 0]
    stealth = fresh.copy()
    fi = stealth.index[stealth.label == 1]
    donors = legit.sample(len(fi), replace=True, random_state=seed).reset_index(drop=True)
    for j, idx in enumerate(fi):
        for c in rng.choice(CONTROLLABLE, size=int(rng.integers(3, len(CONTROLLABLE) + 1)), replace=False):
            stealth.at[idx, c] = donors.at[j, c]
    return fresh, stealth


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="datasets/synthetic_credit_boost")
    ap.add_argument("--v2", default=str(HERE.parent / "models" / "credit_brain_v2.json"))
    ap.add_argument("--out", default=str(HERE.parent / "models" / "credit_brain_v3.json"))
    ap.add_argument("--report-dir", default=str(HERE.parent / "benchmarks" / "credit_v3"))
    ap.add_argument("--stress-seed", type=int, default=777001)
    ap.add_argument("--stress-rows", type=int, default=10000)
    ap.add_argument("--n-estimators", type=int, default=300)
    a = ap.parse_args()
    from lightgbm import LGBMClassifier
    import lightgbm

    v2 = json.loads(Path(a.v2).read_text(encoding="utf-8"))
    td = v2["training_data"]
    tr, va, te, ho = v2_splits(Path(a.data), td["adaptive_train_frac"])
    if (len(tr), len(va), len(te), len(ho)) != (td["train_rows"], td["val_rows"], td["test_rows"],
                                                td["adaptive_holdout_rows"]):
        raise SystemExit("split mismatch vs credit_brain_v2.json")
    Xtr, Xva = matrix(tr), matrix(va)
    ytr, yva = tr["label"].to_numpy(), va["label"].to_numpy()

    t0 = time.perf_counter()
    lgbm = LGBMClassifier(n_estimators=a.n_estimators, num_leaves=31, learning_rate=0.05, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8, min_child_samples=50, n_jobs=16,
                          random_state=0, verbose=-1).fit(Xtr, ytr)
    train_s = time.perf_counter() - t0
    dump = lgbm.booster_.dump_model()
    trees = [flatten(t) for t in dump["tree_info"]]
    t_low, t_high = pick_thresholds(yva, lgbm.predict_proba(Xva)[:, 1])

    model = {"features": v2["features"]}
    model.update({
        "model_version": "credit-brain-lgbm-v3",
        "kind": "lightgbm_trees_stdlib",
        "tree_init": 0.0, "trees": trees,
        "reason_codes": "Saabas path attribution on the same trees (sums exactly to the logit)",
        "thresholds": {"t_low": float(t_low), "t_high": float(t_high), "chosen_on": "val",
                       "val_fpr_target": v2["thresholds"]["val_fpr_target"],
                       "val_recall_target": v2["thresholds"]["val_recall_target"]},
        "training_data": td,
        "versions": {"python": platform.python_version(), "lightgbm": lightgbm.__version__},
        "caveat": v2["caveat"],
    })
    assert model["features"] == FEATURES
    out = Path(a.out)
    out.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")

    b2, b3 = CreditBrain(v2), CreditBrain.load(out)
    Xte = matrix(te)
    p3 = np.array([b3.score(r)[0] for r in te.to_dict("records")])
    parity = float(np.max(np.abs(p3 - lgbm.predict_proba(Xte)[:, 1])))

    fresh, stealth = stress_sets(a.stress_seed, a.stress_rows, 0.07)
    sets = {"test": te, "adaptive_holdout": ho, "stress_fresh_rings": fresh, "stress_stealth_graft": stealth}
    res = {}
    for name, brain in (("v2_lr", b2), ("v3_lgbm", b3)):
        res[name] = {}
        for k, d in sets.items():
            p = np.array([brain.score(r)[0] for r in d.to_dict("records")])
            rep = decision_report(brain, d)
            rep.pop("by_typology", None)
            res[name][k] = {**ranking(d["label"].to_numpy(), p), **rep}
        recs = te.to_dict("records")[:2000]
        for r in recs[:50]:
            brain.assess(r)
        t = []
        for r in recs:
            s = time.perf_counter_ns(); brain.assess(r); t.append((time.perf_counter_ns() - s) / 1e6)
        res[name]["assess_latency_ms"] = {q: round(float(np.percentile(t, int(q[1:]))), 4) for q in ("p50", "p95", "p99")}

    report = {"caveat": "SYNTHETIC DATA ONLY.", "lgbm_train_seconds": round(train_s, 2), "n_trees": len(trees),
              "stdlib_vs_lightgbm_max_abs_prob_diff_test": parity, "thresholds_v3": model["thresholds"],
              "stress": {"seed": a.stress_seed, "rows": a.stress_rows, "controllable_fields": CONTROLLABLE},
              "model_bytes": out.stat().st_size, "results": res}
    rd = Path(a.report_dir); rd.mkdir(parents=True, exist_ok=True)
    (rd / "credit_v3_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    w = lambda x: "n/a" if x is None else x[0]  # noqa: E731
    lines = ["# Credit brain v2 (LR) vs v3 candidate (LightGBM, stdlib trees) - SYNTHETIC", "",
             f"stdlib-vs-lightgbm parity max |dp| {parity:.2e}; {len(trees)} trees; model {report['model_bytes']} bytes.", "",
             "| model | set | PR-AUC | recall(any) | FPR(any) | recall(review) | FPR(review) |", "|---|---|---|---|---|---|---|"]
    for n, sets_ in res.items():
        for k, m in sets_.items():
            if k == "assess_latency_ms":
                continue
            lines.append(f"| {n} | {k} | {m['pr_auc']} | {w(m['recall_any_action'])} | {w(m['fpr_any_action'])} | "
                         f"{w(m['recall_manual_review'])} | {w(m['fpr_manual_review'])} |")
    lines += ["", "| model | assess p50 ms | p95 | p99 |", "|---|---|---|---|"]
    lines += [f"| {n} | {r['assess_latency_ms']['p50']} | {r['assess_latency_ms']['p95']} | {r['assess_latency_ms']['p99']} |"
              for n, r in res.items()]
    (rd / "credit_v3_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
