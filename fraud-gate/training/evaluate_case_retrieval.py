"""Measure case-memory retrieval quality/latency against real Redis and real payload text.

Corpus = text_train rows written as analyst-verdict archetypes; queries = sampled text_test rows.
Scenarios:
  full_corpus   - matcher sees every candidate (quality ceiling, bypasses the 128 bound)
  legacy_page   - candidates = first 128 index ids (the pre-v4 behavior)
  lsh_buckets   - candidates = LSH collision-ranked ids (the v4 behavior)
Matchers: hashed (default fallback) or neural (bi-encoder + cross-encoder rerank), optionally a
fine-tuned bi-encoder from train_contrastive.py. All numbers are measured; nothing is fabricated.

Run a local Redis first, e.g.:  docker run -d --rm -p 6399:6379 redis:7-alpine
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.case_matching import (  # noqa: E402
    CaseCandidate,
    HashedCaseMatcher,
    SentenceTransformerCaseMatcher,
    _cosine,
    hashed_vector,
    query_text,
)
from app.case_memory import RedisCaseMemory  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("payload", "").strip()]


def to_case(row: dict, index: int) -> dict:
    features = {"payload_chars": len(row["payload"])}
    verdict = "FRAUD" if row["label"] == "1" else "BENIGN"
    return {
        "order_id": f"eval-order-{index}",
        "decision_id": f"eval-decision-{index}",
        "archetype_id": f"full-{index}",
        "verdict": verdict,
        "telemetry": features,
        "text": row["payload"][:2000],
    }


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(q * len(ordered)) - 1))
    return round(ordered[index], 2)


async def main_async(args: argparse.Namespace) -> dict:
    import redis.asyncio as aioredis

    client = aioredis.from_url(args.redis_url)
    await client.flushdb()
    matcher_name = args.matcher
    if matcher_name == "hashed":
        matcher = HashedCaseMatcher()
    else:
        matcher = SentenceTransformerCaseMatcher(
            args.bi_encoder, args.cross_encoder,
            embedding_cache_size=args.embedding_cache_size, rerank_top_k=args.rerank_top_k,
        )
    memory = RedisCaseMemory(client, matcher=matcher, prefix="eval:case-memory")

    train = load_rows(Path(args.splits_dir) / "text_train.csv")[: args.corpus_limit]
    test = load_rows(Path(args.splits_dir) / "text_test.csv")
    random.Random(13).shuffle(test)
    queries = test[: args.queries]

    insert_started = time.perf_counter()
    for index, row in enumerate(train):
        await memory.update_from_analyst_verdict(**to_case(row, index))
    insert_seconds = time.perf_counter() - insert_started

    candidates = [
        CaseCandidate(
            case_id=f"full-{index}",
            text=query_text(case["text"], case["telemetry"]),
            features=case["telemetry"],
            verdict=case["verdict"],
        )
        for index, case in ((index, to_case(row, index)) for index, row in enumerate(train))
    ]

    query_rows = []
    for row in queries:
        features = {"payload_chars": len(row["payload"])}
        query_rows.append({
            "text": query_text(row["payload"][:2000], features),
            "features": features,
            "verdict": "FRAUD" if row["label"] == "1" else "BENIGN",
        })

    # Ground truth: brute-force similarity over the full corpus (matcher-native scoring).
    if matcher_name == "hashed":
        corpus_vectors = [hashed_vector(case.text) for case in candidates]

        def similarities(text: str) -> list[float]:
            vector = hashed_vector(text)
            return [_cosine(vector, other) for other in corpus_vectors]
    else:
        corpus_vectors = await asyncio.to_thread(
            matcher._candidate_vectors, [case.text for case in candidates]
        )

        def similarities(text: str) -> list[float]:
            vector = matcher._encode([text])[0]
            return [(_cosine(vector, other) + 1.0) / 2.0 for other in corpus_vectors]

    truth_top10 = []
    for row in query_rows:
        sims = await asyncio.to_thread(similarities, row["text"])
        order = sorted(range(len(candidates)), key=lambda i: (-sims[i], candidates[i].case_id))
        truth_top10.append({candidates[i].case_id: candidates[i].verdict for i in order[:10]})

    async def run_scenario(name: str) -> dict:
        if name == "full_corpus":
            async def one(row):
                return await matcher.match(row["text"], row["features"], candidates, limit=5)
        else:
            strategy = "first_page" if name == "legacy_page" else "lsh"
            scenario_memory = RedisCaseMemory(client, matcher=matcher,
                                              prefix="eval:case-memory", candidate_strategy=strategy)

            async def one(row):
                return await scenario_memory.match(row["text"], row["features"], limit=5)

        await one(query_rows[0])  # warm caches/model
        latencies, recalls, verdict_hits, vote_hits = [], [], [], []
        for row, truth in zip(query_rows, truth_top10):
            started = time.perf_counter()
            result = await one(row)
            latencies.append((time.perf_counter() - started) * 1000)
            recalled = sum(
                1 for match in result.matches
                if match.case_id in truth and truth[match.case_id] == match.verdict
            )
            recalls.append(recalled / 5)
            verdict_hits.append(recalled / len(result.matches) if result.matches else 0.0)
            fraud = sum(1 for match in result.matches if match.verdict == "FRAUD")
            majority = "FRAUD" if fraud > len(result.matches) / 2 else "BENIGN"
            vote_hits.append(float(bool(result.matches) and majority == row["verdict"]))
        return {
            "queries": len(query_rows),
            "recall_at_5_vs_full_corpus_top10": round(statistics.mean(recalls), 4),
            "verdict_precision_at_5": round(statistics.mean(verdict_hits), 4),
            "majority_vote_accuracy_at_5": round(statistics.mean(vote_hits), 4),
            "latency_ms": {"p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95),
                           "max": round(max(latencies), 2)},
        }

    scenarios = {}
    for name in ("full_corpus", "legacy_page", "lsh_buckets"):
        scenarios[name] = await run_scenario(name)
        print(f"{name}: {json.dumps(scenarios[name])}", flush=True)

    report = {
        "matcher": matcher_name,
        "bi_encoder": args.bi_encoder if matcher_name != "hashed" else None,
        "cross_encoder": args.cross_encoder if matcher_name != "hashed" else None,
        "embedding_cache_size": args.embedding_cache_size if matcher_name != "hashed" else None,
        "rerank_top_k": args.rerank_top_k if matcher_name != "hashed" else None,
        "corpus_rows": len(train),
        "corpus_insert_seconds": round(insert_seconds, 1),
        "embedding_cache": {
            "hits": getattr(matcher, "cache_hits", None),
            "misses": getattr(matcher, "cache_misses", None),
        },
        "scenarios": scenarios,
        "note": "verdicts are L4 labels mapped to FRAUD/BENIGN; text is payload + canonical telemetry, "
                "so this measures retrieval machinery on real text, not analyst-confirmed fraud cases",
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    await client.aclose()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--redis-url", default="redis://localhost:6399/0")
    parser.add_argument("--splits-dir", required=True)
    parser.add_argument("--matcher", choices=["hashed", "neural"], default="hashed")
    parser.add_argument("--bi-encoder", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--cross-encoder", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    parser.add_argument("--embedding-cache-size", type=int, default=8192)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--corpus-limit", type=int, default=6200)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--output")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main_async(args)), indent=2))


if __name__ == "__main__":
    main()
