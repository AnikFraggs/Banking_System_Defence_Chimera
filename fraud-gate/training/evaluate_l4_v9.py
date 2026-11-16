from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from transformers import AutoTokenizer
from xgboost import XGBClassifier

from l4_v9 import (FEATURE_NAMES, MONOTONE, OUT, ROOT, cutoff, digest, encode_views,
                   group_folds, lex_features, metrics, read_rows, save_json, score_onnx,
                   session, stacker_predict)

V8 = ROOT / "build-check/l4_v8/out_v8"
V6 = ROOT / "build-check/l4_distill/out_minilm_l12_v2"
V9 = OUT / "out_v9"
BASE = ROOT / "datasets/new_custom_datasets/out/v5"


def wilson(k, n):
    z = 1.959963984540054
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [center - radius, center + radius]


def full_metrics(scores, labels, cut):
    m = metrics(scores, labels, cut)
    if m["n_pos"]:
        m["recall_wilson95"] = wilson(m["tp"], m["n_pos"])
    if m["n_neg"]:
        m["fpr_wilson95"] = wilson(m["fp"], m["n_neg"])
    return m


def spml_systems():
    raw = ROOT / "datasets/new_custom_datasets/raw/spml/train.jsonl"
    systems = []
    with raw.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                systems.append(json.loads(line).get("System Prompt") or None)
    return systems


def attach_systems(rows, systems):
    out = []
    for r in rows:
        r = dict(r)
        rid = r.get("id", "")
        if isinstance(rid, str) and rid.startswith("spml-"):
            idx = int(rid.split("-")[1])
            if idx < len(systems):
                r["system"] = systems[idx]
        out.append(r)
    return out


def feature_matrix(rows, ma, mb, lex_logit):
    feats = []
    for i, r in enumerate(rows):
        f = lex_features(r["text"], r.get("system"))
        f[0], f[1], f[2] = ma[i], mb[i], lex_logit[i]
        feats.append(f)
    return np.asarray(feats, dtype=np.float64)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-data", action="store_true")
    args = parser.parse_args()
    if not args.authorized_data:
        raise SystemExit("--authorized-data required")
    if (OUT / "evaluation.json").exists():
        raise SystemExit("evaluation already locked; refuse implicit test retuning")
    manifest = json.loads((OUT / "data_manifest.json").read_text())
    protocol = json.loads((OUT / "protocol.json").read_text())
    for path, sha in manifest["locked"].items():
        if digest(ROOT / path) != sha:
            raise SystemExit(f"locked data changed: {path}")
    for name, sha in manifest["outputs"].items():
        if digest(OUT / f"{name}.jsonl") != sha:
            raise SystemExit(f"v9 data changed: {name}")
    if not (V9 / "model.onnx").exists():
        raise SystemExit("v9 model not exported yet")
    tok = AutoTokenizer.from_pretrained(str(V8 / "hf_checkpoint"), local_files_only=True)
    systems = spml_systems()

    cal_rows = {
        "internal": list(read_rows(BASE / "l4_v5_calib.jsonl")),
        "external": attach_systems(list(read_rows(BASE / "l4_v5_external_calib.jsonl")), systems),
        "v8new": list(read_rows(ROOT / "build-check/l4_v8/new_calib.jsonl")),
        "v9new": list(read_rows(OUT / "new_calib.jsonl")),
        "paired": list(read_rows(OUT / "paired_calib.jsonl")),
    }
    test_rows = {
        "internal": list(read_rows(BASE / "l4_v5_test.jsonl")),
        "external": attach_systems(list(read_rows(BASE / "l4_v5_external_test.jsonl")), systems),
        "v8new": list(read_rows(ROOT / "build-check/l4_v8/new_test.jsonl")),
        "v9new": list(read_rows(OUT / "new_test.jsonl")),
        "paired": list(read_rows(OUT / "paired_test.jsonl")),
    }
    train_rows = list(read_rows(OUT / "train.jsonl"))
    meta_rows = list(read_rows(OUT / "meta.jsonl"))

    sessions = {name: session(d / "model.onnx") for name, d in (("v6", V6), ("v8", V8), ("v9", V9))}
    import onnx
    for name, d in (("v6", V6), ("v8", V8), ("v9", V9)):
        model = onnx.load(str(d / "model.onnx"))
        onnx.checker.check_model(model)
        if next(v.version for v in model.opset_import if v.domain in ("", "ai.onnx")) != 17:
            raise SystemExit(f"{name} opset != 17")
        if digest(d / "vocab.txt") != digest(V6 / "vocab.txt"):
            raise SystemExit("vocab drift")

    def neural(name, rows, view):
        idx, enc = encode_views(tok, rows, view)
        if not idx:
            return np.full(len(rows), np.nan)
        scores = np.full(len(rows), np.nan)
        scores[idx] = score_onnx(sessions[name], enc)
        return scores

    report = {"protocol_sha256": digest(OUT / "protocol.json"), "data_manifest_sha256": digest(OUT / "data_manifest.json"),
              "models": {}, "stacker": {}, "data_sha256": {}}
    all_rows = {**{f"cal_{k}": v for k, v in cal_rows.items()}, **{f"test_{k}": v for k, v in test_rows.items()}}
    report["data_sha256"] = {k: digest(OUT / f"{k}.jsonl") for k in ("train", "meta", "new_calib", "new_test", "paired_calib", "paired_test")}

    # ---- neural margins (int8 ONNX, batch1, single thread), cached ----
    cache_path = OUT / "neural_margins.npz"
    margins = {}
    if cache_path.exists():
        z = np.load(cache_path)
        for name in ("v6", "v8", "v9"):
            margins[name] = {}
            for key in all_rows:
                margins[name][key] = {"a": z[f"{name}|{key}|a"]}
                if name == "v9":
                    margins[name][key]["b"] = z[f"{name}|{key}|b"]
        print("loaded cached neural margins", flush=True)
    else:
        flat = {}
        for name in ("v6", "v8", "v9"):
            margins[name] = {}
            for key, rows in all_rows.items():
                margins[name][key] = {"a": neural(name, rows, "a")}
                flat[f"{name}|{key}|a"] = margins[name][key]["a"]
                if name == "v9":
                    margins[name][key]["b"] = neural(name, rows, "b")
                    flat[f"{name}|{key}|b"] = margins[name][key]["b"]
            print(f"scored {name}", flush=True)
        np.savez_compressed(cache_path, **flat)

    # ---- ProtectAI rival (CPU torch fp32, batch1) ----
    import torch
    from transformers import AutoModelForSequenceClassification
    torch.set_num_threads(16)
    pdir = ROOT / "fraud-gate/training/benchmarks/rivals/protectai_deberta_v3"
    ptok = AutoTokenizer.from_pretrained(str(pdir), local_files_only=True)
    pcache = OUT / "protectai_margins.npz"
    cached = dict(np.load(pcache)) if pcache.exists() else {}
    margins["protectai"] = {}
    pending = [k for k in all_rows if f"{k}|a" not in cached]
    pmodel = AutoModelForSequenceClassification.from_pretrained(str(pdir), local_files_only=True).eval() if pending else None
    with torch.inference_mode():
        for key, rows in all_rows.items():
            if f"{key}|a" in cached:
                margins["protectai"][key] = {"a": cached[f"{key}|a"], "b": cached[f"{key}|b"]}
                continue
            ma, mb = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
            for i, r in enumerate(rows):
                enc = ptok(r["text"][:8192], truncation=True, max_length=512, return_tensors="pt")
                enc.pop("token_type_ids", None)
                logits = pmodel(**enc).logits[0]
                ma[i] = float(logits[1] - logits[0])
                if r.get("system"):
                    encb = ptok(r["system"][:8192], r["text"][:8192], truncation=True, max_length=512, return_tensors="pt")
                    encb.pop("token_type_ids", None)
                    lb = pmodel(**encb).logits[0]
                    mb[i] = float(lb[1] - lb[0])
            margins["protectai"][key] = {"a": ma, "b": mb}
            cached[f"{key}|a"], cached[f"{key}|b"] = ma, mb
            np.savez_compressed(pcache, **cached)
            print(f"protectai {key}", flush=True)
    del pmodel
    report["protectai_scoring"] = "GPU bf16 batch32 via score_protectai_v9_gpu.py (cached); not int8, not in the 250ms gate"

    # ---- lexical baseline: TFIDF+LR fit on TRAIN only ----
    train_texts = [r["text"] for r in train_rows if r["label_a"] is not None]
    train_labels = np.array([r["label_a"] for r in train_rows if r["label_a"] is not None])
    tfidf = TfidfVectorizer(ngram_range=(1, 3), max_features=50000, sublinear_tf=True)
    X = tfidf.fit_transform(train_texts)
    lr = LogisticRegression(C=1.0, max_iter=1000)
    lr.fit(X, train_labels)

    def lex_logit(rows):
        return lr.decision_function(tfidf.transform([r["text"] for r in rows]))

    # ---- stacker fit on META only, GroupKFold OOF ----
    meta_ma = margins["v9"]["cal_meta"] if "cal_meta" in margins["v9"] else neural("v9", meta_rows, "a")
    meta_mb = neural("v9", meta_rows, "b")
    meta_lex = lex_logit(meta_rows)
    meta_X = feature_matrix(meta_rows, meta_ma, meta_mb, meta_lex)
    meta_y = np.array([r["label"] for r in meta_rows])
    meta_groups = np.array([r["group"] for r in meta_rows])
    folds = group_folds(meta_groups, 5)
    oof = np.full(len(meta_rows), np.nan)
    fold_models = []
    for tr, va in folds:
        if len(set(meta_y[tr])) < 2:
            raise SystemExit("fold lacks both classes")
        clf = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=.1,
                            monotone_constraints=tuple(MONOTONE), tree_method="hist",
                            missing=np.nan, n_jobs=8, random_state=13, eval_metric="logloss")
        clf.fit(meta_X[tr], meta_y[tr])
        oof[va] = clf.predict_proba(meta_X[va])[:, 1]
        fold_models.append(clf)
    oof_cut = cutoff([oof], [meta_y], protocol["calibration_fpr_budget"])
    ensemble_meta = stacker_predict(fold_models, meta_X)
    report["stacker"] = {"oof_cut": oof_cut, "oof_metrics": full_metrics(oof, meta_y, oof_cut),
                         "ensemble_on_meta": full_metrics(ensemble_meta, meta_y, oof_cut),
                         "n_groups": int(len(set(meta_groups))), "feature_names": FEATURE_NAMES}

    # ---- calibration cuts ----
    def cal_features(name, key, view="a"):
        rows = cal_rows[key]
        ma = margins[name][f"cal_{key}"]["a"]
        mb = margins[name][f"cal_{key}"].get("b", np.full(len(rows), np.nan)) if name in ("v9", "protectai") else np.full(len(rows), np.nan)
        return feature_matrix(rows, ma, mb, lex_logit(rows))

    cuts = {}
    for name in ("v6", "v8", "protectai"):
        scores = [margins[name][f"cal_{k}"]["a"] for k in cal_rows]
        labels = [np.array([r["label"] for r in cal_rows[k]]) for k in cal_rows]
        cuts[name] = cutoff(scores, labels, protocol["calibration_fpr_budget"])
    cuts["v9_a"] = cutoff([margins["v9"][f"cal_{k}"]["a"] for k in cal_rows if k != "paired"],
                          [np.array([r["label"] for r in cal_rows[k]]) for k in cal_rows if k != "paired"],
                          protocol["calibration_fpr_budget"])
    cuts["v9_b"] = cutoff([margins["v9"]["cal_paired"]["b"]], [np.array([r["label"] for r in cal_rows["paired"]])], protocol["calibration_fpr_budget"])
    cal_stack_scores = [stacker_predict(fold_models, cal_features("v9", k)) for k in cal_rows]
    cal_stack_labels = [np.array([r["label"] for r in cal_rows[k]]) for k in cal_rows]
    ensemble_cal_cut = cutoff(cal_stack_scores, cal_stack_labels, protocol["calibration_fpr_budget"])
    cuts["v9_hybrid"] = max(oof_cut, ensemble_cal_cut)
    report["cuts"] = cuts
    report["stacker"]["ensemble_cal_cut"] = ensemble_cal_cut
    report["stacker"]["final_cut"] = cuts["v9_hybrid"]

    # ---- calibration report ----
    for name in ("v6", "v8", "protectai", "v9_a", "v9_hybrid"):
        report["models"].setdefault(name, {"calibration": {}, "tests": {}})
        for k in cal_rows:
            if name == "v9_hybrid":
                s = stacker_predict(fold_models, cal_features("v9", k))
            elif name == "v9_a":
                s = margins["v9"][f"cal_{k}"]["a"]
            else:
                s = margins[name][f"cal_{k}"]["a"]
            y = np.array([r["label"] for r in cal_rows[k]])
            report["models"][name]["calibration"][k] = full_metrics(s, y, cuts[name])
    report["models"]["v9_b"] = {"calibration": {"paired": full_metrics(margins["v9"]["cal_paired"]["b"], np.array([r["label"] for r in cal_rows["paired"]]), cuts["v9_b"])}, "tests": {}}
    report["models"]["protectai_b"] = {"calibration": {}, "tests": {}}
    pb_cal = margins["protectai"]["cal_paired"]["b"]
    pb_y = np.array([r["label"] for r in cal_rows["paired"]])
    valid = np.isfinite(pb_cal)
    pb_cut = cutoff([pb_cal[valid]], [pb_y[valid]], protocol["calibration_fpr_budget"])
    report["models"]["protectai_b"]["calibration"]["paired"] = full_metrics(pb_cal[valid], pb_y[valid], pb_cut)
    report["cuts"]["protectai_b"] = pb_cut

    # ---- holdouts (scored once) ----
    for k, rows in test_rows.items():
        y = np.array([r["label"] for r in rows])
        for name in ("v6", "v8", "protectai"):
            s = margins[name][f"test_{k}"]["a"]
            report["models"][name]["tests"][k] = full_metrics(s, y, cuts[name])
            np.savez_compressed(OUT / f"pred_{name}_{k}.npz", scores=s, labels=y)
        sa = margins["v9"][f"test_{k}"]["a"]
        report["models"]["v9_a"]["tests"][k] = full_metrics(sa, y, cuts["v9_a"])
        sb = margins["v9"][f"test_{k}"]["b"]
        if np.isfinite(sb).any():
            report["models"]["v9_b"]["tests"][k] = full_metrics(sb[np.isfinite(sb)], y[np.isfinite(sb)], cuts["v9_b"])
        mbp = margins["protectai"][f"test_{k}"]["b"]
        if np.isfinite(mbp).any():
            report["models"]["protectai_b"]["tests"][k] = full_metrics(mbp[np.isfinite(mbp)], y[np.isfinite(mbp)], pb_cut)
        feats = feature_matrix(rows, sa, sb, lex_logit(rows))
        sh = stacker_predict(fold_models, feats)
        report["models"]["v9_hybrid"]["tests"][k] = full_metrics(sh, y, cuts["v9_hybrid"])
        np.savez_compressed(OUT / f"pred_v9hybrid_{k}.npz", scores=sh, labels=y)
        print(f"test {k} done", flush=True)

    # ---- monotonicity + NaN-B checks ----
    probe = feature_matrix([{"text": "hello", "system": None}], np.array([0.]), np.array([np.nan]), np.array([0.]))
    base_p = stacker_predict(fold_models, probe)[0]
    mono_ok = True
    for col in (0, 2):
        up = probe.copy(); up[0, col] += 2.0
        if stacker_predict(fold_models, up)[0] < base_p - 1e-9:
            mono_ok = False
    report["stacker"]["monotone_mA_lexlogit"] = mono_ok
    report["stacker"]["nan_b_finite"] = bool(np.isfinite(base_p))

    # ---- latency (single-thread CPU, batch1) ----
    text = "review this banking support request " * 40
    lat = {}
    for name in ("v6", "v8", "v9"):
        _, enc = encode_views(tok, [{"text": text}], "a")
        for _ in range(25):
            score_onnx(sessions[name], enc)
        samples = []
        for _ in range(200):
            t0 = time.perf_counter()
            encode_views(tok, [{"text": text}], "a")
            score_onnx(sessions[name], enc)
            samples.append((time.perf_counter() - t0) * 1000)
        lat[name + "_a"] = {"p50": float(np.percentile(samples, 50)), "p95": float(np.percentile(samples, 95))}
    _, encb = encode_views(tok, [{"text": text, "system": "answer finance only"}], "b")
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        score_onnx(sessions["v9"], encb)
        samples.append((time.perf_counter() - t0) * 1000)
    lat["v9_b_onnx"] = {"p50": float(np.percentile(samples, 50)), "p95": float(np.percentile(samples, 95))}
    report["latency_ms"] = lat

    # ---- gates ----
    holdouts = ["internal", "external", "v8new", "v9new", "paired"]
    hy, v8m, v6m = report["models"]["v9_hybrid"]["tests"], report["models"]["v8"]["tests"], report["models"]["v6"]["tests"]
    gates = {
        "all_holdout_fpr_at_most_2pct": all(hy[k]["fpr"] <= .02 for k in holdouts),
        "no_recall_regression_vs_v8": all(hy[k]["recall"] >= v8m[k]["recall"] for k in holdouts),
        "no_recall_regression_vs_v6": all(hy[k]["recall"] >= v6m[k]["recall"] for k in holdouts),
        "higher_mean_recall_vs_v8": sum(hy[k]["recall"] for k in holdouts) > sum(v8m[k]["recall"] for k in holdouts),
        "cpu_p95_below_250ms": lat["v9_a"]["p95"] < 250,
    }
    ext = report["models"]["v9_hybrid"]["tests"]["external"]
    report["offline_gates"] = gates
    report["offline_candidate_passed"] = all(gates.values())
    report["promoted"] = False
    report["runtime_g1"] = "NOT_MEASURED"
    report["limitations"] = [
        "No Robots CC-BY-NC-4.0: research-only, not commercially cleared regardless of gates.",
        "Hybrid stacker + paired view are not implemented in the Java runtime; not a drop-in deployment.",
        "ProtectAI rival scored GPU bf16 batch32 (cached); not int8; its latency not in the 250ms gate.",
        "External paired view uses recovered SPML system prompts by row id; payload-only labels retained for A view.",
        "Synthetic paired slices are authored templates, not independent human-reviewed SPML.",
        "Wilson intervals assume independent rows; skeleton grouping does not prove semantic independence.",
        "No Prompt Guard specialist teacher or XSTest hard negatives (gated).",
    ]
    save_json(OUT / "evaluation.json", report)
    print(json.dumps({"cuts": cuts, "gates": gates}, indent=2), flush=True)


if __name__ == "__main__":
    main()
