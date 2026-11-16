"""Build contrastive pairs for train_contrastive.py from the L4 text splits.

Pairs are two different payloads from the same (sub_source, label) group in text_train,
serialized with the same canonical telemetry prefix the case memory uses. Test/dev rows
are never used. This is style/origin supervision: it teaches the bi-encoder what
"similar case" means for this corpus, not analyst-confirmed fraud similarity.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.case_matching import query_text  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pairs-per-group", type=int, default=500)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    with (Path(args.splits_dir) / "text_train.csv").open(newline="", encoding="utf-8") as handle:
        groups = defaultdict(list)
        for row in csv.DictReader(handle):
            payload = row.get("payload", "").strip()
            if payload:
                groups[(row["sub_source"], row["label"])].append(payload)

    rng = random.Random(args.seed)
    seen: set[tuple[str, str]] = set()
    pairs = []
    for (source, label), payloads in sorted(groups.items()):
        if len(payloads) < 2:
            continue
        rng.shuffle(payloads)
        for index in range(min(args.pairs_per_group, len(payloads) // 2)):
            anchor_payload, positive_payload = payloads[2 * index], payloads[2 * index + 1]
            anchor = query_text(anchor_payload[:2000], {"payload_chars": len(anchor_payload)})
            positive = query_text(positive_payload[:2000], {"payload_chars": len(positive_payload)})
            key = (anchor, positive)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({
                "scenario_id": f"{source.replace('/', '_')}-{label}-{index}",
                "anchor": anchor[:16000],
                "positive": positive[:16000],
            })
    if len(pairs) < 2:
        raise SystemExit("need at least two pairs")
    rng.shuffle(pairs)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(json.dumps({"pairs": len(pairs), "groups": len(groups), "output": args.output}, indent=2))


if __name__ == "__main__":
    main()
