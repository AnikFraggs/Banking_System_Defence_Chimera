from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build-check/l4_v9"
FEATURE_NAMES = ["m_a", "m_b", "lex_logit", "n_chars", "n_words", "n_lines", "word_len_mean", "upper_ratio", "digit_ratio", "punct_ratio", "nonascii_ratio", "char_entropy", "cue_override", "cue_roleplay", "cue_extract", "cue_delimiter", "cue_imperative", "has_b64", "has_hex", "has_url", "has_codefence", "sys_words", "payload_sys_ratio", "cue_density"]
MONOTONE = [1, 1, 1] + [0] * 21
PATTERNS = {
    "override": r"\b(ignore|disregard|forget|bypass|override|disable)\b|\bdo not follow\b|\b(previous|prior|initial|above|earlier)\s+(instructions?|rules?|prompts?)\b",
    "roleplay": r"\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\b|\bdeveloper\s+mode\b|\bjailbreak\b|\bDAN\b",
    "extract": r"\b(reveal|verbatim|leak|expose|disclose|secret|password|confidential|hidden)\b|\bsystem\s+prompt\b",
    "delimiter": r"#{3,}|</?(system|instruction|prompt|user|assistant)>|\[(system|instructions)\]|<{3,}",
    "imperative": r"^\s*(ignore|tell|show|give|write|say|print|reveal|translate|summarize|list|explain|act|pretend|forget|answer|respond)\b",
}


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def norm_hash(text):
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def skeleton_hash(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    skeleton = " ".join("".join(c if c.isalpha() or c.isspace() else " " for c in normalized).split())
    return norm_hash(skeleton) if skeleton else norm_hash(text)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(path):
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            text = raw.get("text", raw.get("payload", ""))
            label = raw.get("label")
            if not isinstance(text, str) or not text.strip() or label not in (0, 1):
                raise ValueError(f"Invalid labelled text in {path}")
            yield {**raw, "text": text, "label": int(label), "system": raw.get("system") or None,
                   "label_a": raw.get("label_a", int(label)), "group": raw.get("group", skeleton_hash(text))}


def save_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def cutoff(score_sets, label_sets, budget=.01):
    if not 0 <= budget < 1 or len(score_sets) != len(label_sets):
        raise ValueError("Invalid calibration budget or slices")
    cuts = []
    for scores, labels in zip(score_sets, label_sets):
        scores, labels = np.asarray(scores), np.asarray(labels)
        if not len(scores) or not np.isfinite(scores).all() or len(scores) != len(labels):
            raise ValueError("Invalid calibration scores")
        negatives = np.sort(scores[labels == 0])[::-1]
        if len(negatives):
            cuts.append(float(negatives[math.floor(budget * len(negatives))]))
    if not cuts:
        raise ValueError("Calibration requires benign examples")
    return max(cuts)


def metrics(scores, labels, cut):
    from sklearn.metrics import average_precision_score, roc_auc_score
    scores, labels = np.asarray(scores), np.asarray(labels)
    predicted = scores > cut
    pos, neg = int(sum(labels == 1)), int(sum(labels == 0))
    tp, fp = int(sum(predicted & (labels == 1))), int(sum(predicted & (labels == 0)))
    return {"n_pos": pos, "n_neg": neg, "tp": tp, "fp": fp, "recall": tp / pos if pos else None,
            "fpr": fp / neg if neg else None,
            "roc_auc": float(roc_auc_score(labels, scores)) if pos and neg else None,
            "average_precision": float(average_precision_score(labels, scores)) if pos and neg else None}


def encode_views(tok, rows, view="a"):
    if view not in ("a", "b"):
        raise ValueError("Unknown view")
    length = 128 if view == "a" else 192
    indices, ids, segments, masks = [], [], [], []
    for i, row in enumerate(rows):
        if view == "b" and not row.get("system"):
            continue
        text = unicodedata.normalize("NFKC", row["text"][:8192])
        if view == "a":
            payload = tok(text, add_special_tokens=False, truncation=True, max_length=126)["input_ids"]
            tokens = [tok.cls_token_id] + payload + [tok.sep_token_id]
            seg = [0] * len(tokens)
        else:
            system = tok(unicodedata.normalize("NFKC", row["system"][:8192]), add_special_tokens=False, truncation=True, max_length=96)["input_ids"]
            payload = tok(text, add_special_tokens=False, truncation=True, max_length=length - len(system) - 3)["input_ids"]
            tokens = [tok.cls_token_id] + system + [tok.sep_token_id] + payload + [tok.sep_token_id]
            seg = [0] * (len(system) + 2) + [1] * (len(payload) + 1)
        indices.append(i)
        ids.append(tokens + [tok.pad_token_id] * (length - len(tokens)))
        segments.append(seg + [0] * (length - len(seg)))
        masks.append([1] * len(tokens) + [0] * (length - len(tokens)))
    values = np.asarray(ids, dtype=np.int64).reshape(-1, length)
    return indices, {"input_ids": values, "attention_mask": np.asarray(masks, dtype=np.int64).reshape(-1, length),
                     "token_type_ids": np.asarray(segments, dtype=np.int64).reshape(-1, length)}


def teacher_windows(tok, rows, view):
    indices, encoded = encode_views(tok, rows, view)
    texts = []
    for j, i in enumerate(indices):
        ids = encoded["input_ids"][j]
        mask = encoded["attention_mask"][j].astype(bool)
        ids = ids[mask].tolist()
        if view == "a":
            texts.append(tok.decode(ids[1:-1], skip_special_tokens=False))
        else:
            boundary = int(np.flatnonzero(encoded["token_type_ids"][j] == 1)[0]) - 1
            system = tok.decode(ids[1:boundary], skip_special_tokens=False)
            payload = tok.decode(ids[boundary + 1:-1], skip_special_tokens=False)
            texts.append((system, payload))
    return indices, texts


def gates(margins, offsets, labels, sources, view):
    if np.shape(margins) != (len(labels), 2) or len(sources) != len(labels) or not np.isfinite(offsets).all():
        raise ValueError("Teacher alignment or calibration invalid")
    centered = np.clip(margins, -20, 20) - np.asarray(offsets)
    weights = np.isfinite(centered).astype(np.float32)
    for i, (label, source) in enumerate(zip(labels, sources)):
        if label is None:
            weights[i] = 0
            continue
        weights[i] *= ((centered[i] > 0) == (label == 1))
        if any(s in source.casefold() for s in ("hackaprompt", "jailbreak", "gandalf", "tensor_trust")):
            weights[i, 0] = 0
        if view == "b":
            weights[i, 1] = 0
    return np.nan_to_num(centered, nan=0.0).astype(np.float32), weights


def lex_features(text, system=None):
    n, words = max(len(text), 1), text.split()
    nw = max(len(words), 1)
    counts = Counter(text)
    cues = {name: len(re.findall(pattern, text, re.I | re.M)) for name, pattern in PATTERNS.items()}
    total = sum(cues[name] for name in ("override", "roleplay", "extract", "delimiter"))
    sw = len(system.split()) if system else None
    return [np.nan, np.nan, np.nan, len(text), len(words), text.count("\n") + 1, sum(map(len, words)) / nw,
            sum(c.isupper() for c in text) / n, sum(c.isdigit() for c in text) / n,
            sum(not c.isalnum() and not c.isspace() for c in text) / n, sum(ord(c) > 127 for c in text) / n,
            -sum(c / n * math.log2(c / n) for c in counts.values()),
            *[cues[k] for k in ("override", "roleplay", "extract", "delimiter", "imperative")],
            float(bool(re.search(r"[A-Za-z0-9+/]{40,}={0,2}", text))),
            float(bool(re.search(r"(?:0x)?[0-9a-fA-F]{32,}", text))),
            float(bool(re.search(r"https?://|www\.", text))), float("```" in text or "~~~" in text),
            sw if sw is not None else np.nan, len(words) / max(sw, 1) if sw is not None else np.nan, total / nw]


def session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def score_onnx(sess, encoded):
    scores = []
    for i in range(len(encoded["input_ids"])):
        logits = sess.run(["logits"], {k: v[i:i + 1] for k, v in encoded.items()})[0]
        if logits.shape != (1, 2) or not np.isfinite(logits).all():
            raise ValueError("Invalid ONNX binary output")
        scores.append(float(logits[0, 1] - logits[0, 0]))
    return np.asarray(scores)


def group_folds(groups, n_splits=5):
    from sklearn.model_selection import GroupKFold
    if len(set(groups)) < n_splits:
        raise ValueError("Not enough independent groups; row-split fallback is prohibited")
    return list(GroupKFold(n_splits=n_splits).split(np.zeros(len(groups)), groups=groups))


def stacker_predict(models, features):
    return np.mean([model.predict_proba(features)[:, 1] for model in models], axis=0)
