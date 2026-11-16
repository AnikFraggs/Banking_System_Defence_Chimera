"""Build a bounded L4 transfer set without moving any locked evaluation rows."""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import re
from collections import Counter
from pathlib import Path


def fingerprint(text):
    return hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()


def group_key(text):
    prefix = re.sub(r"\d+", "#", " ".join(text.casefold().split()))[:96]
    return fingerprint(prefix)


def split_for(group):
    bucket = int(group[:8], 16) % 10
    return "calib" if bucket == 8 else "test" if bucket == 9 else "train"


def offer(heap, row, limit):
    rank = int(fingerprint(row["text"]), 16)
    entry = (-rank, row["text"], row)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
    elif rank < -heap[0][0]:
        heapq.heapreplace(heap, entry)


def build(args):
    if not args.authorized_data:
        raise SystemExit("--authorized-data is required")
    from transformers import AutoTokenizer
    root = Path(args.root).resolve()
    out = root / "build-check/l4_v8"
    if (out / "data_manifest.json").exists():
        raise SystemExit("v8 data already exists; do not overwrite a locked experiment")
    tok = AutoTokenizer.from_pretrained(str(root / "build-check/l4_distill/out_minilm_l12_v2/hf_checkpoint"), local_files_only=True)
    def window_hashes(texts):
        ids = tok(texts, truncation=True, max_length=128, add_special_tokens=True)["input_ids"]
        return [hashlib.sha256(json.dumps(i).encode()).hexdigest() for i in ids]
    locked = list((root / "datasets/new_custom_datasets/out/v5").glob("*.jsonl"))
    locked = [p for p in locked if any(k in p.name for k in ("calib", "test", "external_full"))]
    locked += list((root / "datasets/new_custom_datasets/out/v7").glob("*test*.jsonl"))
    replay_path = root / "build-check/l4_distill/teacher_scores_all.jsonl"
    replay = [json.loads(line) for line in replay_path.read_text(encoding="utf-8").split("\n") if line.strip()]
    reserved_texts = [r.get("text", r.get("payload", "")) for r in replay]
    manifest = {"protocol": "v6 replay + bounded new sources; normalized-text and 128-token-window exclusion; normalized-prefix groups; no SPML training", "locked": {}}
    for path in locked:
        manifest["locked"][str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        reserved_texts.extend(r.get("text", r.get("payload", "")) for r in (json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()))
    forbid = {fingerprint(t) for t in reserved_texts}
    reserved_groups = {group_key(t) for t in reserved_texts}
    windows = set()
    for start in range(0, len(reserved_texts), 512):
        windows.update(window_hashes(reserved_texts[start:start + 512]))
    heaps = {(src, split): [] for src in ("hackaprompt", "web_benign") for split in ("train", "calib", "test")}
    stats = Counter()
    csv.field_size_limit(32 * 1024 * 1024)
    input_files = {"hackaprompt": root / "datasets/hackaprompt_dataset.csv", "web_benign": root / "datasets/web_attack_detection.csv"}
    for src, path in input_files.items():
        seen = set()
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                stats[src + ":read"] += 1
                if src == "hackaprompt":
                    if raw["correct"].lower() != "true" or raw["error"].lower() == "true":
                        continue
                    text, label = raw["user_input"], 1
                else:
                    if raw["Label"] != "0":
                        continue
                    text, label = raw["Sentence"], 0
                if not text.strip() or len(text) > 12000:
                    continue
                h = fingerprint(text)
                if h in forbid or h in seen:
                    stats[src + ":duplicate_or_locked"] += 1
                    continue
                seen.add(h)
                group = group_key(text)
                if group in reserved_groups:
                    stats[src + ":reserved_group"] += 1
                    continue
                split = split_for(group)
                limit = 4000 if split == "train" else 1200
                offer(heaps[src, split], {"text": text, "label": label, "source": src, "group": group}, limit)
    selected = {s: [] for s in ("train", "calib", "test")}
    for (src, split), heap in heaps.items():
        candidates = [entry[2] for entry in sorted(heap, key=lambda e: -e[0])]
        hashes = window_hashes([r["text"] for r in candidates])
        limit = 1500 if split == "train" else 500
        count = 0
        for row, h in zip(candidates, hashes):
            if h in windows:
                stats[src + ":window_overlap"] += 1
                continue
            windows.add(h)
            selected[split].append(row)
            count += 1
            if count == limit:
                break
        stats[src + ":" + split] = count
    groups = {s: {r["group"] for r in rows} for s, rows in selected.items()}
    for a, b in (("train", "calib"), ("train", "test"), ("calib", "test")):
        if groups[a] & groups[b]:
            raise SystemExit("group leakage")
    if any(len(rows) < 200 for rows in selected.values()):
        raise SystemExit("insufficient data after exclusion")
    out.mkdir(exist_ok=True)
    for split, rows in selected.items():
        (out / f"new_{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest.update(stats=dict(stats), replay_sha256=hashlib.sha256(replay_path.read_bytes()).hexdigest(), inputs={s: {"path": str(p.relative_to(root)), "bytes": p.stat().st_size} for s, p in input_files.items()}, limitations=["HackAPrompt correct means attack success, not benign/malicious; failed attacks are excluded, never relabelled benign.", "New groups use normalized text prefixes, not a guarantee of author/template independence.", "Local uploads authorize offline evaluation; redistribution licences still require verification."])
    (out / "data_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--authorized-data", action="store_true")
    build(parser.parse_args())
