"""Train + evaluate a web-attack text classifier (SQLi / XSS / command injection).

Dataset: web_attack_detection.csv (Sentence, Label, Idx). Label 1 = attack,
0 = benign. Sentences are HTTP requests plus general text. Duplicate sentences
are collapsed; sentences with conflicting labels are dropped as ambiguous. The
split is by sentence hash bucket (70/15/15) so identical text never spans splits.

Baseline comparator: a defensive regex web-attack detector. A sampled L4 v6
comparison is included to show the prompt-injection guard is out-of-domain here.
Threshold chosen on calibration only (FPR budget 1%); test scored once.

Run: python train_web_attack.py --authorized-data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets/web_attack_detection.csv"
DEST = ROOT / "fraud-gate/training/artifacts/web_attack_guard"
FPR_BUDGET = 0.01

REGEX = re.compile(
    r"(union\s+(all\s+)?select|select\s+.*\s+from\s+|information_schema|or\s+1\s*=\s*1|"
    r"'\s*or\s*'|sleep\s*\(|benchmark\s*\(|ctxsys\.|rdb\$fields|;\s*--|\bdrop\s+table\b|"
    r"<\s*script|javascript\s*:|onerror\s*=|onload\s*=|document\.cookie|alert\s*\(|"
    r"<\s*img[^>]+onerror|\.\./|\.\.\\|/etc/passwd|\bcmd\s*=|exec\s*\(|\beval\s*\(|"
    r"\$\(|`[^`]*`|\|\s*cat\b|&&\s*whoami|;\s*ls\b)", re.IGNORECASE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bucket(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % 100


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
            "f1": float(f1_score(labels, pred)), "tp": tp, "fp": fp, "tn": tn, "fn": fn}


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
    nun = df.groupby("Sentence")["Label"].nunique()
    ambiguous = set(nun[nun > 1].index)
    df = df[~df["Sentence"].isin(ambiguous)].drop_duplicates("Sentence").reset_index(drop=True)
    texts = df["Sentence"].tolist()
    y = df["Label"].to_numpy()
    b = np.array([bucket(t) for t in texts])
    train_m, calib_m, test_m = b < 70, (b >= 70) & (b < 85), b >= 85

    model = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                  max_features=200000, sublinear_tf=True, lowercase=True)),
        ("clf", LogisticRegression(C=1.0, max_iter=1000, solver="liblinear", random_state=13)),
    ])
    model.fit([texts[i] for i in np.where(train_m)[0]], y[train_m])
    cal = model.predict_proba([texts[i] for i in np.where(calib_m)[0]])[:, 1]
    cut = cutoff(cal, y[calib_m], FPR_BUDGET)
    test_idx = np.where(test_m)[0]
    test_texts = [texts[i] for i in test_idx]
    test = model.predict_proba(test_texts)[:, 1]
    result = {"calibration": metrics(cal, y[calib_m], cut), "test": metrics(test, y[test_m], cut)}
    print("tfidf_lr", json.dumps(result["test"]), flush=True)

    # Defensive regex baseline on the same test split.
    rx = np.array([1.0 if REGEX.search(t) else 0.0 for t in test_texts])
    pos, neg = y[test_m] == 1, y[test_m] == 0
    tp = int((rx[pos] == 1).sum()); fp = int((rx[neg] == 1).sum())
    fn = int((rx[pos] == 0).sum()); tn = int((rx[neg] == 0).sum())
    regex_result = {"recall": tp / max(tp + fn, 1), "fpr": fp / max(fp + tn, 1),
                    "f1": float(f1_score(y[test_m], rx)), "tp": tp, "fp": fp, "tn": tn, "fn": fn}
    print("regex_baseline", json.dumps(regex_result), flush=True)

    # Sampled L4 v6 comparison (prompt-injection guard, out-of-domain here).
    l4_result = {"note": "sampled comparison; L4 v6 is a prompt-injection guard, not a web-attack detector"}
    try:
        import sys
        sys.path.insert(0, str(ROOT / "fraud-gate/training"))
        from l4_v9 import encode_views, session, score_onnx
        from transformers import AutoTokenizer
        v6 = ROOT / "build-check/l4_distill/out_minilm_l12_v2"
        tok = AutoTokenizer.from_pretrained(str(v6 / "hf_checkpoint"), local_files_only=True)
        sess = session(v6 / "model.onnx")
        rng = np.random.default_rng(13)
        pos_idx = rng.choice(np.where(test_m & (y == 1))[0], size=min(1000, int((test_m & (y == 1)).sum())), replace=False)
        neg_idx = rng.choice(np.where(test_m & (y == 0))[0], size=min(1000, int((test_m & (y == 0)).sum())), replace=False)
        sidx = np.concatenate([pos_idx, neg_idx])
        rows = [{"text": texts[i][:8192]} for i in sidx]
        _, enc = encode_views(tok, rows, "a")
        margins = score_onnx(sess, enc)
        l4cut = -12.611477851867676
        pred = margins > l4cut
        sy = y[sidx]
        sp, sn = sy == 1, sy == 0
        l4_result.update({"sample_pos": int(sp.sum()), "sample_neg": int(sn.sum()),
                          "recall": float(pred[sp].mean()), "fpr": float(pred[sn].mean()),
                          "threshold_logit_margin": l4cut})
        print("l4_v6_sample", json.dumps(l4_result), flush=True)
    except Exception as e:  # noqa: BLE001 - comparison is optional
        l4_result["error"] = str(e)

    beats = (result["test"]["average_precision"] > 0.5
             and result["test"]["recall"] >= regex_result["recall"]
             and result["test"]["fpr"] <= regex_result["fpr"] + 1e-9)

    import joblib
    artifact = DEST / "model.joblib"
    joblib.dump(model, artifact)
    metadata = {
        "version": "web-attack-tfidf-lr-v1",
        "dataset": "datasets/web_attack_detection.csv",
        "dataset_sha256": digest(DATA),
        "label_meaning": "Label 1 = attack (SQLi/XSS/command injection), 0 = benign",
        "rows_raw": 625904, "unique_sentences": int(len(df)),
        "dropped_ambiguous_sentences": len(ambiguous),
        "positives": int(y.sum()), "prevalence": float(y.mean()),
        "split": {"method": "sha256(sentence) bucket 70/15/15", "train": int(train_m.sum()),
                  "calibration": int(calib_m.sum()), "test": int(test_m.sum())},
        "model": "TfidfVectorizer char_wb(3,5) max200000 sublinear + LogisticRegression liblinear C=1",
        "fpr_budget_calibration": FPR_BUDGET,
        "selection": "calibration-only threshold; test scored once",
        "results": {"tfidf_lr": result, "regex_baseline": regex_result, "l4_v6_sample": l4_result},
        "beats_regex_baseline": bool(beats),
        "artifact_sha256": digest(artifact),
        "limitations": [
            "exact-duplicate dedup only; near-duplicate attack templates may span splits",
            "mixed HTTP requests and general text; not a pure web-attack corpus",
            "L4 v6 comparison is out-of-domain (prompt injection) and sampled",
            "research only; verify label meanings and licence before production use",
        ],
    }
    (DEST / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print("beats_regex", beats, "artifact", digest(artifact), flush=True)


if __name__ == "__main__":
    main()