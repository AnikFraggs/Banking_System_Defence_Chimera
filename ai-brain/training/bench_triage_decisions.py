"""End-to-end /v1/triage decisions on the rag_eval test split: regex-only vs the deployed hybrid.

Calls app.triage exactly as the API does, once with the hybrid disabled and once with the deployed
models/rag_reranker.json + models/bge_small encoder. Nothing is fitted here; test split only.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-brain"))

import app as brain_app  # noqa: E402
from rag_engine import HybridRetriever  # noqa: E402

EVAL = ROOT / "datasets/new_custom_datasets/out/rag_eval/rag_eval.jsonl"
OUT = ROOT / "ai-brain/benchmarks/rag/triage_decisions.json"
ORDER = ("allow", "step_up", "constrain", "isolate_session")


def decide(rows, rag, challenge_weight):
    brain_app.RAG, brain_app.CHALLENGE_WEIGHT = rag, challenge_weight
    out = {}
    for kind in ("attack", "benign"):
        subset = [r for r in rows if bool(r["gold"]) == (kind == "attack")]
        counts, escalated_by_source = Counter(), defaultdict(lambda: [0, 0])
        for r in subset:
            body = brain_app.triage(brain_app.TriageRequest(telemetry={"payload": r["text"]}))
            counts[body["enforced_recommendation"]] += 1
            escalated_by_source[r["source"]][0] += body["enforced_recommendation"] != "allow"
            escalated_by_source[r["source"]][1] += 1
        n = len(subset)
        out[kind] = {"n": n, **{d: round(counts[d] / n, 4) for d in ORDER},
                     "escalated_rate": round(1 - counts["allow"] / n, 4),
                     "human_review_rate": round((counts["constrain"] + counts["isolate_session"]) / n, 4),
                     "escalated_by_source": {s: round(a / b, 4) for s, (a, b) in sorted(escalated_by_source.items())}}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--what-if-challenge-weight", type=float,
                    help="also report the deployed hybrid with this CHALLENGE_WEIGHT (policy what-if)")
    args = ap.parse_args()
    test = [r for r in map(json.loads, EVAL.open(encoding="utf-8")) if r["split"] == "test"]
    deployed = HybridRetriever.load(brain_app.KNOWLEDGE)
    if not deployed.loaded:
        sys.exit("deployed hybrid not loaded: need models/rag_reranker.json and models/bge_small")
    weight = brain_app.CHALLENGE_WEIGHT
    report = {"eval_file": str(EVAL.relative_to(ROOT)), "split": "test", "dense_backend": deployed.dense_backend,
              "thresholds": {k: deployed.model[k] for k in ("challenge_threshold", "block_threshold")},
              "variants": {"regex_only": decide(test, HybridRetriever(brain_app.KNOWLEDGE), weight),
                           f"deployed_union_challenge_weight_{weight}": decide(test, deployed, weight)}}
    if args.what_if_challenge_weight is not None:
        w = args.what_if_challenge_weight
        report["variants"][f"what_if_challenge_weight_{w}"] = decide(test, deployed, w)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, v in report["variants"].items():
        print(name, {k: {m: v[k][m] for m in ("n", *ORDER, "escalated_rate", "human_review_rate")} for k in v})


if __name__ == "__main__":
    main()
