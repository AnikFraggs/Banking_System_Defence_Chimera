"""Hybrid retrieval over the triage knowledge base (offline, no external calls).

BM25 over word + symbol tokens and a 384-d dense vector are fused with reciprocal rank fusion
(k=60); a logistic reranker (weights in models/rag_reranker.json, fitted on the dev split by
training/bench_rag.py) turns per-class evidence into a probability. The deployed dense encoder is
bge-small-en-v1.5 int8 ONNX (models/bge_small, training/export_bge_onnx.py); the stdlib signed-hash
char 3-5-gram vector is the benchmark baseline. Text is canonicalized (NFKC, zero-width removal,
URL/HTML decoding) and PAN/email-redacted before use.
"""
from __future__ import annotations

import html
import json
import math
import re
import time
import unicodedata
import urllib.parse
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

DIM = 384
RRF_K = 60
TOP_DOCS = 10
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "rag_reranker.json"
DEFAULT_DENSE_DIR = Path(__file__).resolve().parent / "models" / "bge_small"
FEATURES = ("dense_max", "bm25_log", "rrf", "coverage", "regex_hit")

_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff]")
_TOKEN = re.compile(r"[a-z0-9_@]+|[^\sa-z0-9_@]{1,3}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_DIGIT_RUN = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def redact(text: str) -> str:
    text = _EMAIL.sub("<email>", text)
    return _DIGIT_RUN.sub(
        lambda m: "<pan>" if _luhn_ok(re.sub(r"\D", "", m.group())) else m.group(), text)


def canonical(text: str) -> str:
    text = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text))
    for _ in range(2):
        decoded = html.unescape(urllib.parse.unquote_plus(text))
        if decoded == text:
            break
        text = decoded
    return redact(text).lower()


def tokens(text: str) -> List[str]:
    return _TOKEN.findall(text)


def hashed_vector(text: str) -> List[float]:
    vec = [0.0] * DIM
    padded = f" {text} "
    grams: Counter = Counter()
    for n in (3, 4, 5):
        for i in range(len(padded) - n + 1):
            grams[padded[i:i + n]] += 1
    for gram, tf in grams.items():
        h = zlib.crc32(gram.encode("utf-8", "surrogatepass"))
        vec[h % DIM] += (1.0 + math.log(tf)) * (1.0 if (h >> 16) & 1 else -1.0)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


class OnnxEmbedder:
    """bge-small-en-v1.5 int8 ONNX (CLS pooling, L2-normalised), exported by training/export_bge_onnx.py."""

    def __init__(self, model_dir: Path, max_length: int = 256):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self.session = ort.InferenceSession(str(model_dir / "model_int8.onnx"), opts,
                                            providers=["CPUExecutionProvider"])

    def __call__(self, texts: List[str]) -> List[List[float]]:
        np = self._np
        out: List[List[float]] = []
        for i in range(0, len(texts), 64):
            enc = self.tokenizer.encode_batch(texts[i:i + 64])
            feeds = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                     "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
                     "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64)}
            out += self.session.run(None, feeds)[0].tolist()
        return out


class HybridRetriever:
    def __init__(self, knowledge: Sequence[Dict[str, Any]], model: Optional[Dict[str, Any]] = None,
                 embed: Optional[Callable[[List[str]], List[List[float]]]] = None, use_docs: bool = True):
        self.entries = {e["id"]: e for e in knowledge}
        self._patterns = {e["id"]: [re.compile(p, re.IGNORECASE) for p in e["patterns"]] for e in knowledge}
        self.doc_class: List[str] = []
        doc_texts: List[str] = []
        for e in knowledge:
            texts = [e["name"] + ". " + e["mitigation"]]
            if use_docs:
                texts += e.get("docs", [])
            for t in texts:
                self.doc_class.append(e["id"])
                doc_texts.append(canonical(t))
        self._embed = embed or (lambda texts: [hashed_vector(t) for t in texts])
        self.doc_vecs = self._embed(doc_texts)
        self.doc_tf = [Counter(tokens(t)) for t in doc_texts]
        self.doc_len = [sum(tf.values()) for tf in self.doc_tf]
        self.avg_len = sum(self.doc_len) / len(self.doc_len)
        df: Counter = Counter()
        for tf in self.doc_tf:
            df.update(tf.keys())
        n = len(self.doc_tf)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.model = model

    @classmethod
    def load(cls, knowledge: Sequence[Dict[str, Any]], path: Path = DEFAULT_MODEL_PATH,
             dense_dir: Path = DEFAULT_DENSE_DIR) -> "HybridRetriever":
        """Reranker weights are specific to their dense backend, so a missing encoder disables the hybrid."""
        model = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        embed = None
        if model is not None and model.get("dense") == "bge_small_onnx_int8":
            if (dense_dir / "model_int8.onnx").exists():
                embed = OnnxEmbedder(dense_dir)
            else:
                model = None
        elif model is not None and model.get("dense") != "hashed":
            model = None
        retriever = cls(knowledge, model, embed)
        retriever.dense_backend = model["dense"] if model else None
        return retriever

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def _bm25(self, q_terms: Counter) -> List[float]:
        k1, b = 1.2, 0.75
        scores = []
        for tf, dl in zip(self.doc_tf, self.doc_len):
            s = 0.0
            for t in q_terms:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self.avg_len))
            scores.append(s)
        return scores

    def analyse(self, text: str, query_vec: Optional[List[float]] = None) -> Dict[str, Any]:
        """Per-class feature vectors plus the RRF-fused document ranking."""
        q = canonical(text)
        q_tokens = tokens(q)
        q_terms = Counter(q_tokens)
        bm25 = self._bm25(q_terms)
        qv = query_vec if query_vec is not None else self._embed([q])[0]
        dense = [sum(a * b for a, b in zip(qv, dv)) for dv in self.doc_vecs]
        rrf = [0.0] * len(dense)
        for scores in (bm25, dense):
            for rank, i in enumerate(sorted(range(len(scores)), key=lambda i: -scores[i]), start=1):
                rrf[i] += 1.0 / (RRF_K + rank)
        coverage = []
        for tf in self.doc_tf:
            total = sum(self.idf[t] for t in tf)
            coverage.append(sum(self.idf[t] for t in tf if t in q_terms) / total if total else 0.0)
        ranked_docs = sorted(range(len(rrf)), key=lambda i: -rrf[i])
        top = set(ranked_docs[:TOP_DOCS])
        feats: Dict[str, List[float]] = {}
        for cid in self.entries:
            idx = [i for i, c in enumerate(self.doc_class) if c == cid]
            in_top = [i for i in idx if i in top] or idx
            regex = 1.0 if any(p.search(q) for p in self._patterns[cid]) else 0.0
            feats[cid] = [
                max(dense[i] for i in idx),
                math.log1p(max(bm25[i] for i in idx)),
                max(rrf[i] for i in in_top) * RRF_K,
                max(coverage[i] for i in idx),
                regex,
            ]
        return {"features": feats, "ranked_docs": ranked_docs}

    def probabilities(self, feats: Dict[str, List[float]]) -> Dict[str, float]:
        w, bias = self.model["weights"], self.model["bias"]
        return {cid: _sigmoid(bias + sum(a * b for a, b in zip(w, f))) for cid, f in feats.items()}

    def retrieve(self, text: str) -> List[Dict[str, Any]]:
        """Classes whose reranked probability clears the calibrated challenge threshold, strongest first."""
        if self.model is None or not text:
            return []
        started = time.perf_counter()
        analysis = self.analyse(text)
        probs = self.probabilities(analysis["features"])
        challenge, block = self.model["challenge_threshold"], self.model["block_threshold"]
        elapsed_ms = (time.perf_counter() - started) * 1000
        hits = []
        for cid, p in sorted(probs.items(), key=lambda kv: -kv[1]):
            if p >= challenge:
                evidence = [i for i in analysis["ranked_docs"][:TOP_DOCS] if self.doc_class[i] == cid][:3]
                hits.append({"id": cid, "probability": round(p, 4),
                             "band": "block" if p >= block else "challenge",
                             "evidence_docs": evidence, "latency_ms": round(elapsed_ms, 3)})
        return hits
