"""Build the v4 L4 semantic-guard training set without touching the locked test split.

Changes vs v1 (which trained on text_train rows <= 2000 chars only):
  * long rows are truncated to 2000 chars instead of dropped (the model reads 128 tokens anyway);
  * text_dev is split by id hash: half is mined (v1 errors repeated x3) and added to train,
    the other half is kept for threshold calibration only;
  * weak sources from the v1 per-source error table are repeated x2 (deepset, jackhhao malicious,
    synthetic);
  * optional --extra JSONL (your own licensed rows) is added to train only;
  * optional SPML becomes an external held-out set, exact-deduplicated against every split.
Every output row is checked against test/calibration/external so nothing evaluated is trained on.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

MAX_CHARS = 2000
MAX_REPEAT = 5
SOURCE_REPEAT = {
    ("deepset/prompt-injections", 0): 2,
    ("deepset/prompt-injections", 1): 2,
    ("jackhhao/jailbreak-classification", 1): 2,
    ("synthetic", 0): 2,
    ("synthetic", 1): 2,
}
MINED_REPEAT = 3

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).casefold()).strip()


def digest(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def read_split(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {"id": row["id"], "text": row["payload"], "label": int(row["label"]),
             "source": row.get("sub_source") or row.get("source") or "unknown"}
            for row in csv.DictReader(handle) if row.get("payload", "").strip()
        ]


def read_spml(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            record = json.loads(line)
            text = (record.get("User Prompt") or "").strip()
            label = record.get("Prompt injection")
            if not text or label not in (0, 1):
                continue
            origin = "spml_gandalf" if (record.get("Source") or "") == "Gandalf" else "spml_native"
            rows.append({"id": f"spml-{index}", "text": text, "label": int(label), "source": origin,
                         "degree": record.get("Degree")})
    return rows


def read_extra(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            text, label = record.get("text"), record.get("label")
            if not isinstance(text, str) or not text.strip() or label not in (0, 1):
                raise ValueError(f"{path}:{number} needs text and label 0|1")
            rows.append({"id": f"extra-{number}", "text": text, "label": label,
                         "source": str(record.get("source", "extra"))})
    return rows


def in_calibration(row_id: str) -> bool:
    return int(hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:8], 16) % 2 == 1


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(args: argparse.Namespace) -> dict:
    splits = Path(args.splits_dir)
    train = read_split(splits / "text_train.csv")
    dev = read_split(splits / "text_dev.csv")
    test = read_split(splits / "text_test.csv")
    dev_mine = [row for row in dev if not in_calibration(row["id"])]
    calib = [row for row in dev if in_calibration(row["id"])]

    mined_ids: set[str] = set()
    mining = None
    if args.mine_model:
        try:
            from .score_l4_onnx import OnnxScorer
        except ImportError:
            from score_l4_onnx import OnnxScorer  # type: ignore

        scorer = OnnxScorer(args.mine_model, args.mine_tokenizer)
        probs = scorer.predict([row["text"] for row in dev_mine])
        errors = Counter()
        for row, prob in zip(dev_mine, probs):
            if (prob >= args.mine_threshold) != (row["label"] == 1):
                mined_ids.add(row["id"])
                errors[("FP" if row["label"] == 0 else "FN", row["source"])] += 1
        mining = {"rows_scored": len(dev_mine), "errors": len(mined_ids),
                  "by_type_source": {f"{k[0]}:{k[1]}": v for k, v in sorted(errors.items())}}

    blocked = {digest(row["text"]) for row in test + calib}
    external: list[dict] = []
    external_dropped = 0
    if args.spml:
        known = blocked | {digest(row["text"]) for row in train + dev_mine}
        seen: set[str] = set()
        for row in read_spml(Path(args.spml)):
            key = digest(row["text"])
            if key in known or key in seen:
                external_dropped += 1
                continue
            seen.add(key)
            external.append(row)
        blocked |= seen

    candidates = [(row, "train") for row in train] + [(row, "dev_mine") for row in dev_mine]
    if args.extra:
        candidates += [(row, "extra") for row in read_extra(Path(args.extra))]

    merged: dict[str, dict] = {}
    conflicts: set[str] = set()
    leaked = 0
    for row, origin in candidates:
        text = row["text"].strip()[:MAX_CHARS].strip()
        key = digest(text)
        if key in blocked or digest(row["text"]) in blocked:
            leaked += 1
            continue
        repeat = SOURCE_REPEAT.get((row["source"], row["label"]), 1)
        if row["id"] in mined_ids:
            repeat = max(repeat, MINED_REPEAT)
        previous = merged.get(key)
        if previous is not None:
            if previous["label"] != row["label"]:
                conflicts.add(key)
            previous["repeat"] = min(MAX_REPEAT, max(previous["repeat"], repeat))
            continue
        merged[key] = {"text": text, "label": row["label"], "repeat": min(MAX_REPEAT, repeat),
                       "source": row["source"], "origin": origin}
    train_rows = [row for key, row in merged.items() if key not in conflicts]

    out = Path(args.output_dir)
    files = {
        "l4_v4_train.jsonl": write_jsonl(out / "l4_v4_train.jsonl", train_rows),
        "l4_v4_calib.jsonl": write_jsonl(out / "l4_v4_calib.jsonl", [
            {"id": r["id"], "payload": r["text"], "label": r["label"], "source": r["source"]} for r in calib]),
        "l4_v4_test.jsonl": write_jsonl(out / "l4_v4_test.jsonl", [
            {"id": r["id"], "payload": r["text"], "label": r["label"], "source": r["source"]} for r in test]),
    }
    if external:
        files["l4_v4_external.jsonl"] = write_jsonl(out / "l4_v4_external.jsonl", [
            {"id": r["id"], "payload": r["text"], "label": r["label"], "source": r["source"],
             "degree": r["degree"]} for r in external])

    train_keys = set(merged) - conflicts
    leakage = {
        "train_vs_test": len(train_keys & {digest(r["text"]) for r in test}),
        "train_vs_calib": len(train_keys & {digest(r["text"]) for r in calib}),
        "train_vs_external": len(train_keys & {digest(r["text"]) for r in external}),
    }
    if any(leakage.values()):
        raise SystemExit(f"leakage detected: {leakage}")
    manifest = {
        "version": args.version,
        "train_rows_unique": len(train_rows),
        "train_rows_after_repeat": sum(row["repeat"] for row in train_rows),
        "train_by_origin": dict(Counter(row["origin"] for row in train_rows)),
        "train_by_source_label": {f"{s}|{l}": n for (s, l), n in
                                  sorted(Counter((r["source"], r["label"]) for r in train_rows).items())},
        "truncated_rows": sum(1 for row, _ in candidates if len(row["text"].strip()) > MAX_CHARS),
        "label_conflicts_dropped": len(conflicts),
        "rows_blocked_as_eval_overlap": leaked,
        "calibration_rows": len(calib),
        "test_rows": len(test),
        "external_rows": len(external),
        "external_dropped_overlap_or_dup": external_dropped,
        "external_by_source_label": {f"{s}|{l}": n for (s, l), n in
                                     sorted(Counter((r["source"], r["label"]) for r in external).items())},
        "mining": mining,
        "leakage_exact_normalized": leakage,
        "files_sha256": files,
    }
    (out / "MANIFEST_V4.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--splits-dir", required=True, help="dir with text_train/dev/test.csv from chimera_datasets build")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--version", default="l4-v4-data")
    parser.add_argument("--spml", help="raw/spml/train.jsonl -> external held-out set")
    parser.add_argument("--extra", help="extra licensed JSONL {text,label,source} added to train only")
    parser.add_argument("--mine-model", help="current model.int8.onnx used to mine dev errors")
    parser.add_argument("--mine-tokenizer", help="current encoder/ dir")
    parser.add_argument("--mine-threshold", type=float, default=0.65)
    args = parser.parse_args()
    if bool(args.mine_model) != bool(args.mine_tokenizer):
        parser.error("--mine-model and --mine-tokenizer go together")
    print(json.dumps(build(args), indent=2))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
