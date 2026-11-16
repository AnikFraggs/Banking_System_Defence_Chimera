"""Benchmark the SHIPPED credit brain (JSON LR, stdlib inference) against ONNX Runtime serving.

Reproduces the exact v2 splits (ring-grouped adaptive holdout), asserts they match the row counts
recorded in the model file, then compares:
  * json_lr      shipped artifact via CreditBrain.score (what app.py serves today)
  * onnx_lr      the same weights as a hand-built ONNX graph (parity + latency check)
  * onnx_mlp     a small MLP trained on the same train split, exported to ONNX (DL candidate)
  * hgb / lgbm   tree rivals (python-only; reference ceiling)
Thresholds for new candidates are picked on val with the trainer's rule; never on test/holdout.
SYNTHETIC DATA ONLY: numbers show recovery of the generator's signal, not real-world quality.
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
import onnx
import onnxruntime as ort
import pandas as pd
from onnx import TensorProto, helper, numpy_helper
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.neural_network import MLPClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from credit_brain import FEATURES, CreditBrain, red_flags  # noqa: E402
from train_credit_brain import adaptive_ring_split, matrix, pick_thresholds, wilson  # noqa: E402


def v2_splits(data: Path, frac: float):
    df = pd.read_csv(data / "credit_apps.csv")
    adaptive = pd.read_csv(data / "credit_apps_adaptive.csv")
    adaptive_train, holdout = adaptive_ring_split(adaptive, frac)

    def train_or_val(ring_id: str) -> str:
        b = int(hashlib.sha256(f"split|{ring_id}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        return "train" if b < 0.8 else "val"

    df = pd.concat([df, adaptive_train.assign(split=adaptive_train["ring_id"].map(train_or_val))],
                   ignore_index=True)
    tr, va, te = (df[df.split == s].reset_index(drop=True) for s in ("train", "val", "test"))
    return tr, va, te, holdout


def _init(name, arr):
    return numpy_helper.from_array(np.asarray(arr, dtype=np.float32), name)


def onnx_from_layers(mean, scale, layers, path: Path) -> None:
    """Standardize -> [MatMul+Add(+Relu)]* -> Sigmoid. layers = [(W[in,out], b[out]), ...]."""
    inits = [_init("mean", mean), _init("scale", scale)]
    nodes = [helper.make_node("Sub", ["x", "mean"], ["xc"]), helper.make_node("Div", ["xc", "scale"], ["h0"])]
    cur = "h0"
    for i, (W, b) in enumerate(layers):
        inits += [_init(f"W{i}", W), _init(f"b{i}", b)]
        nodes += [helper.make_node("MatMul", [cur, f"W{i}"], [f"m{i}"]),
                  helper.make_node("Add", [f"m{i}", f"b{i}"], [f"a{i}"])]
        cur = f"a{i}"
        if i < len(layers) - 1:
            nodes.append(helper.make_node("Relu", [cur], [f"r{i}"]))
            cur = f"r{i}"
    nodes.append(helper.make_node("Sigmoid", [cur], ["prob"]))
    g = helper.make_graph(nodes, "credit_brain",
                          [helper.make_tensor_value_info("x", TensorProto.FLOAT, ["N", len(mean)])],
                          [helper.make_tensor_value_info("prob", TensorProto.FLOAT, ["N", 1])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)], producer_name="chimera-bench", ir_version=8)
    onnx.checker.check_model(m)
    onnx.save(m, str(path))


def session(path: Path) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def ranking(y, p) -> dict:
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4), "pr_auc": round(float(average_precision_score(y, p)), 4)}


def decisions(p, hard, t_low, t_high) -> np.ndarray:
    return np.where(hard | (p >= t_high), 2, np.where(p >= t_low, 1, 0))


def decision_metrics(y, d) -> dict:
    act, rev = d >= 1, d == 2
    pos, neg = y == 1, y == 0
    return {"recall_any_action": wilson(int((act & pos).sum()), int(pos.sum())),
            "recall_manual_review": wilson(int((rev & pos).sum()), int(pos.sum())),
            "fpr_any_action": wilson(int((act & neg).sum()), int(neg.sum())),
            "fpr_manual_review": wilson(int((rev & neg).sum()), int(neg.sum()))}


def lat(fn, samples, n=2000) -> dict:
    idx = np.linspace(0, len(samples) - 1, min(n, len(samples)), dtype=int)
    for i in idx[:20]:
        fn(samples[i])
    t = []
    for i in idx:
        s = time.perf_counter_ns(); fn(samples[i]); t.append((time.perf_counter_ns() - s) / 1e6)
    return {"p50": round(float(np.percentile(t, 50)), 4), "p95": round(float(np.percentile(t, 95)), 4),
            "p99": round(float(np.percentile(t, 99)), 4)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="datasets/synthetic_credit_boost")
    ap.add_argument("--model", default=str(ROOT / "models" / "credit_brain_v2.json"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)

    shipped = json.loads(Path(a.model).read_text(encoding="utf-8"))
    td = shipped["training_data"]
    tr, va, te, ho = v2_splits(Path(a.data), td["adaptive_train_frac"])
    got = (len(tr), len(va), len(te), len(ho))
    want = (td["train_rows"], td["val_rows"], td["test_rows"], td["adaptive_holdout_rows"])
    if got != want:
        raise SystemExit(f"split mismatch {got} != model {want}; not the shipped artifact's splits")

    Xtr, Xva, Xte, Xho = (matrix(d) for d in (tr, va, te, ho))
    ytr, yva, yte, yho = (d["label"].to_numpy() for d in (tr, va, te, ho))
    hard = {k: np.array([any(f["hard"] for f in red_flags(r)) for r in d.to_dict("records")])
            for k, d in (("val", va), ("test", te), ("holdout", ho))}
    brain = CreditBrain(shipped)

    mean, scale = np.array(shipped["mean"]), np.array(shipped["scale"])
    lr_path = out / "credit_brain_v2_lr.onnx"
    onnx_from_layers(mean, scale, [(np.array(shipped["coef"]).reshape(-1, 1), [shipped["intercept"]])], lr_path)
    s_lr = session(lr_path)

    mlp = MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, learning_rate_init=1e-3, max_iter=300,
                        early_stopping=True, validation_fraction=0.1, n_iter_no_change=15,
                        random_state=a.seed).fit((Xtr - mean) / scale, ytr)
    mlp_path = out / "credit_brain_mlp.onnx"
    onnx_from_layers(mean, scale, list(zip(mlp.coefs_, mlp.intercepts_)), mlp_path)
    s_mlp = session(mlp_path)

    def ort_p(s, X):
        return s.run(None, {"x": X.astype(np.float32)})[0][:, 0].astype(float)

    def json_p(df):
        return np.array([brain.score(r)[0] for r in df.to_dict("records")])

    scorers = {
        "json_lr_shipped": lambda X, df: json_p(df),
        "onnx_lr": lambda X, df: ort_p(s_lr, X),
        "onnx_mlp_64x32": lambda X, df: ort_p(s_mlp, X),
    }
    hgb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=a.seed).fit(Xtr, ytr)
    scorers["hgb_python"] = lambda X, df: hgb.predict_proba(X)[:, 1]
    try:
        from lightgbm import LGBMClassifier
        lgbm = LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.05, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, min_child_samples=50, n_jobs=1, random_state=a.seed,
                              verbose=-1).fit(Xtr, ytr)
        scorers["lightgbm_python"] = lambda X, df: lgbm.predict_proba(X)[:, 1]
    except ImportError:
        pass

    p_json_te = json_p(te)
    parity = {k: float(np.max(np.abs(ort_p(s_lr, X) - json_p(d))))
              for k, X, d in (("test", Xte, te), ("holdout", Xho, ho))}
    d_json = decisions(p_json_te, hard["test"], shipped["thresholds"]["t_low"], shipped["thresholds"]["t_high"])
    d_onnx = decisions(ort_p(s_lr, Xte), hard["test"], shipped["thresholds"]["t_low"], shipped["thresholds"]["t_high"])

    results = {}
    for name, f in scorers.items():
        pva, pte, pho = f(Xva, va), f(Xte, te), f(Xho, ho)
        if name in ("json_lr_shipped", "onnx_lr"):
            t_low, t_high = shipped["thresholds"]["t_low"], shipped["thresholds"]["t_high"]
        else:
            t_low, t_high = pick_thresholds(yva, pva)
        results[name] = {
            "thresholds": {"t_low": round(float(t_low), 6), "t_high": round(float(t_high), 6), "chosen_on": "val"},
            "test": {**ranking(yte, pte), **decision_metrics(yte, decisions(pte, hard["test"], t_low, t_high))},
            "adaptive_holdout": {**ranking(yho, pho),
                                 **decision_metrics(yho, decisions(pho, hard["holdout"], t_low, t_high))},
        }

    recs = te.to_dict("records")
    rows = list(range(len(recs)))
    from credit_brain import featurize
    results["json_lr_shipped"]["latency_ms_single_row_featurize_plus_score"] = lat(lambda i: brain.score(recs[i]), rows)
    for name, s in (("onnx_lr", s_lr), ("onnx_mlp_64x32", s_mlp)):
        results[name]["latency_ms_single_row_featurize_plus_score"] = lat(
            lambda i, s=s: s.run(None, {"x": np.array([featurize(recs[i])], dtype=np.float32)}), rows)
    for name, m in (("hgb_python", hgb), ("lightgbm_python", locals().get("lgbm"))):
        if m is not None and name in results:
            results[name]["latency_ms_single_row_featurize_plus_score"] = lat(
                lambda i, m=m: m.predict_proba(np.array([featurize(recs[i])])), rows)
    results["json_lr_shipped"]["latency_ms_full_assess"] = lat(lambda i: brain.assess(recs[i]), rows)

    report = {
        "caveat": "SYNTHETIC DATA ONLY. Shows recovery of the generator's signal, not real-world quality.",
        "shipped_model": shipped["model_version"],
        "splits_verified_against_model_file": True,
        "rows": dict(zip(("train", "val", "test", "adaptive_holdout"), got)),
        "positives": {"test": int(yte.sum()), "adaptive_holdout": int(yho.sum())},
        "onnx_lr_parity": {"max_abs_prob_diff": parity,
                           "test_decision_agreement": round(float((d_json == d_onnx).mean()), 6)},
        "onnx_files": {"lr": lr_path.name, "mlp": mlp_path.name},
        "environment": {"python": platform.python_version(), "onnxruntime": ort.__version__,
                        "platform": platform.platform(), "ort_threads": 1},
        "models": results,
    }
    (out / "credit_onnx_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def r(w):
        return "n/a" if w is None else w[0]
    lines = ["# Credit brain: shipped JSON LR vs ONNX Runtime serving (SYNTHETIC data)", "",
             f"Splits reproduced and verified against `{shipped['model_version']}`: {report['rows']}.",
             f"ONNX LR parity: max |dp| test {parity['test']:.2e}, holdout {parity['holdout']:.2e}; "
             f"decision agreement {report['onnx_lr_parity']['test_decision_agreement']}.", "",
             "| Model | test ROC | test PR | holdout ROC | holdout PR | holdout recall(any) | holdout FPR(any) "
             "| holdout recall(review) | p50 ms | p99 ms |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n, m in results.items():
        L = m.get("latency_ms_single_row_featurize_plus_score", {})
        h = m["adaptive_holdout"]
        lines.append(f"| {n} | {m['test']['roc_auc']} | {m['test']['pr_auc']} | {h['roc_auc']} | {h['pr_auc']} | "
                     f"{r(h['recall_any_action'])} | {r(h['fpr_any_action'])} | {r(h['recall_manual_review'])} | "
                     f"{L.get('p50', '')} | {L.get('p99', '')} |")
    (out / "credit_onnx_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
