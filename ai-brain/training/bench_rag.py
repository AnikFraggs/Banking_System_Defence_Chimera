"""Benchmark triage retrieval: current regex `_retrieve` vs hybrid RAG variants.

Reranker weights and thresholds are fitted on the dev split only; every reported number is on the
test split of datasets/new_custom_datasets/out/rag_eval/rag_eval.jsonl (build_rag_eval.py).
The reranker is fitted on even-indexed dev rows; thresholds are calibrated on odd-indexed dev rows.
Headline thresholds: challenge = lowest t >= 0.5 with dev benign false-hit <= 0.02,
                     block     = lowest t >= 0.85 with dev benign false-hit <= 0.005.
Deployed (written to rag_reranker_*.json, used by the union rows): challenge is raised to the
threshold matching the regex's own dev false-hit rate, so the hybrid adds recall without
adding false hits beyond the current system.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-brain"))

import app as brain_app  # noqa: E402
from rag_engine import FEATURES, HybridRetriever, OnnxEmbedder, canonical  # noqa: E402

EVAL = ROOT / "datasets/new_custom_datasets/out/rag_eval/rag_eval.jsonl"
OUT = ROOT / "ai-brain/benchmarks/rag"


def pct(values, q):
    s = sorted(values)
    return round(s[max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))], 3)


def bge_embedder(path: str):
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok, model = AutoTokenizer.from_pretrained(path), AutoModel.from_pretrained(path).eval()

    def embed(texts):
        out = []
        with torch.inference_mode():
            for i in range(0, len(texts), 64):
                enc = tok(texts[i:i + 64], padding=True, truncation=True, max_length=256, return_tensors="pt")
                cls = model(**enc).last_hidden_state[:, 0]
                out += torch.nn.functional.normalize(cls, dim=-1).tolist()
        return out
    return embed


def threshold(benign_max_probs, floor, target):
    desc = sorted(benign_max_probs, reverse=True)
    k = int(target * len(desc))
    return max(floor, math.nextafter(desc[k], 1.0)) if k < len(desc) else floor


def fit(retriever, dev, dev_vecs):
    from sklearn.linear_model import LogisticRegression

    X, y, analyses = [], [], []
    for row, vec in zip(dev, dev_vecs):
        analyses.append(retriever.analyse(row["text"], vec))
    for row, a in list(zip(dev, analyses))[0::2]:
        for cid, f in a["features"].items():
            X.append(f)
            y.append(1 if cid in row["gold"] else 0)
    lr = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X, y)
    retriever.model = {"weights": lr.coef_[0].tolist(), "bias": float(lr.intercept_[0]),
                       "challenge_threshold": 0.5, "block_threshold": 0.85}
    benign = [max(retriever.probabilities(a["features"]).values())
              for row, a in list(zip(dev, analyses))[1::2] if not row["gold"]]
    retriever.model["challenge_threshold"] = threshold(benign, 0.5, 0.02)
    retriever.model["block_threshold"] = threshold(benign, 0.85, 0.005)
    return retriever.model


def evaluate(name, rows, hits_fn, ranking_fn=None):
    attack = [r for r in rows if r["gold"]]
    benign = [r for r in rows if not r["gold"]]
    per_source = defaultdict(lambda: [0, 0])
    recall = strict = fh = 0
    mrr = doc_r10 = ndcg = doc_mrr = 0.0
    lat = []
    for r in rows:
        t0 = time.perf_counter()
        hits = hits_fn(r)
        lat.append((time.perf_counter() - t0) * 1000)
        ids = [h for h in hits]
        if r["gold"]:
            g = r["gold"][0]
            ok = g in ids
            recall += ok
            strict += bool(ids) and ids[0] == g
            per_source[r["source"] + "|attack"][0] += ok
            per_source[r["source"] + "|attack"][1] += 1
            if ranking_fn:
                class_rank, doc_rel = ranking_fn(r)
                mrr += 1.0 / (class_rank.index(g) + 1)
                rel = [1 if c == g else 0 for c in doc_rel[:10]]
                doc_r10 += any(rel)
                first = next((i for i, c in enumerate(doc_rel) if c == g), None)
                doc_mrr += 1.0 / (first + 1) if first is not None else 0.0
                ideal_n = min(10, sum(1 for c in doc_rel if c == g))
                dcg = sum(x / math.log2(i + 2) for i, x in enumerate(rel))
                idcg = sum(1 / math.log2(i + 2) for i in range(ideal_n)) or 1.0
                ndcg += dcg / idcg
        else:
            fh += bool(ids)
            per_source[r["source"] + "|benign"][0] += bool(ids)
            per_source[r["source"] + "|benign"][1] += 1
    n = len(attack)
    out = {
        "variant": name,
        "attack_queries": n, "benign_queries": len(benign),
        "attack_hit_recall": round(recall / n, 4),
        "top_hit_accuracy": round(strict / n, 4),
        "benign_false_hit_rate": round(fh / len(benign), 4),
        "latency_ms": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "max": round(max(lat), 3)},
        "per_source_hit_rate": {k: {"rate": round(a / b, 4), "n": b} for k, (a, b) in sorted(per_source.items())},
    }
    if ranking_fn:
        out.update({"class_mrr": round(mrr / n, 4), "doc_recall_at_10": round(doc_r10 / n, 4),
                    "doc_mrr": round(doc_mrr / n, 4), "doc_ndcg_at_10": round(ndcg / n, 4)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bge", help="local bge-small-en-v1.5 dir; adds the torch fp32 neural-dense variant")
    ap.add_argument("--bge-onnx", help="ai-brain/models/bge_small; adds the deployable int8 ONNX variant")
    args = ap.parse_args()
    rows = [json.loads(l) for l in EVAL.open(encoding="utf-8")]
    dev = [r for r in rows if r["split"] == "dev"]
    test = [r for r in rows if r["split"] == "test"]
    kb = brain_app.KNOWLEDGE
    OUT.mkdir(parents=True, exist_ok=True)

    results = [evaluate("regex_current", test,
                        lambda r: [h["id"] for h in brain_app._retrieve(r["text"].lower())])]

    variants = {"hybrid_hashed_compact_kb": dict(use_docs=False), "hybrid_hashed": dict(use_docs=True)}
    if args.bge:
        variants["hybrid_bge_small"] = dict(use_docs=True, embed=bge_embedder(args.bge))
    if args.bge_onnx:
        variants["hybrid_bge_small_onnx_int8"] = dict(use_docs=True, embed=OnnxEmbedder(Path(args.bge_onnx)))
    models = {}
    for name, kw in variants.items():
        retr = HybridRetriever(kb, **kw)
        embed = kw.get("embed")
        dev_vecs = embed([canonical(r["text"]) for r in dev]) if embed else [None] * len(dev)
        test_vecs = embed([canonical(r["text"]) for r in test]) if embed else [None] * len(test)
        models[name] = fit(retr, dev, dev_vecs)
        vec_of = {id(r): v for r, v in zip(test, test_vecs)}
        cache = {}

        def analyse(r, retr=retr, vec_of=vec_of, cache=cache):
            if id(r) not in cache:
                a = retr.analyse(r["text"], vec_of[id(r)])
                cache[id(r)] = (a, retr.probabilities(a["features"]))
            return cache[id(r)]

        def hits(r, retr=retr, analyse=analyse):
            _, probs = analyse(r)
            th = retr.model["challenge_threshold"]
            return [c for c, p in sorted(probs.items(), key=lambda kv: -kv[1]) if p >= th]

        def ranking(r, retr=retr, analyse=analyse):
            a, probs = analyse(r)
            return sorted(probs, key=lambda c: -probs[c]), [retr.doc_class[i] for i in a["ranked_docs"]]

        res = evaluate(name, test, hits, ranking)
        calib_benign = [r for r in dev[1::2] if not r["gold"]]
        regex_fh = sum(bool(brain_app._retrieve(r["text"].lower())) for r in calib_benign) / len(calib_benign)
        calib_probs = [max(retr.probabilities(retr.analyse(r["text"], v)["features"]).values())
                       for r, v in list(zip(dev, dev_vecs))[1::2] if not r["gold"]]
        t_match = threshold(calib_probs, 0.5, regex_fh)

        def hits_matched(r, analyse=analyse, t=t_match):
            _, probs = analyse(r)
            return [c for c, p in sorted(probs.items(), key=lambda kv: -kv[1]) if p >= t]
        m = evaluate(name, test, hits_matched)
        models[name]["challenge_threshold"] = max(models[name]["challenge_threshold"], t_match)
        models[name]["block_threshold"] = max(models[name]["block_threshold"], t_match)
        res["at_regex_false_hit_rate"] = {"dev_calib_regex_false_hit": round(regex_fh, 4), "threshold": t_match,
                                          "attack_hit_recall": m["attack_hit_recall"],
                                          "benign_false_hit_rate": m["benign_false_hit_rate"]}
        res["thresholds"] = {k: models[name][k] for k in ("challenge_threshold", "block_threshold")}
        res["reranker_weights"] = dict(zip(FEATURES, [round(w, 4) for w in models[name]["weights"]]))
        res["latency_ms_end_to_end"] = evaluate(name, test[::4], lambda r: [h["id"] for h in retr.retrieve(r["text"])])["latency_ms"]
        results.append(res)

        if name in ("hybrid_hashed", "hybrid_bge_small_onnx_int8"):
            def union(r, hits=hits_matched):
                return list(dict.fromkeys(hits(r) + [h["id"] for h in brain_app._retrieve(r["text"].lower())]))
            results.append(evaluate(f"union_regex_plus_{name}", test, union))
        (OUT / f"rag_reranker_{name}.json").write_text(
            json.dumps({**models[name], "features": list(FEATURES),
                        "dense": {"hybrid_bge_small_onnx_int8": "bge_small_onnx_int8",
                                  "hybrid_bge_small": "bge_small_torch_fp32"}.get(name, "hashed"),
                        "fitted_on": "rag_eval dev split", "eval_sha256_manifest": "out/rag_eval/MANIFEST.json"},
                       indent=2) + "\n", encoding="utf-8")

    report = {"eval_file": str(EVAL.relative_to(ROOT)), "dev_rows": len(dev), "test_rows": len(test),
              "protocol": "reranker + thresholds fitted on dev; all metrics on test", "results": results}
    (OUT / "rag_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for r in results:
        print(json.dumps({k: v for k, v in r.items() if k != "per_source_hit_rate"}))


if __name__ == "__main__":
    main()
