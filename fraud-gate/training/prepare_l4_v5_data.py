"""Build the v5 L4 semantic-guard dataset (successor to prepare_l4_v4_data.py).

Changes vs v4:
  * adds JailbreakBench harmful/benign behaviors (hard positives / same-topic hard negatives);
  * adds TrustAIRLab in-the-wild jailbreak + regular prompts (real persona-style attacks, the
    SPML-native failure class); regular-benign additions are capped and hash-sampled (seed-stable);
  * locks a stratified ~20% external CALIBRATION slice of SPML before any training, so v5 can
    calibrate under distribution shift without consuming the external test slice;
  * keeps the full external file for v4-comparable numbers, and writes the external TEST slice
    (the remaining ~80%) as the honest generalization set;
  * every training row is hash-checked against test / in-domain calib / ALL external rows.

This script only prepares data. It never trains a model. Mining (--mine-model) scores the dev
half with an existing artifact to repeat its errors; it does not fit anything.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

try:
    from .prepare_l4_v4_data import (MAX_CHARS, MAX_REPEAT, MINED_REPEAT, SOURCE_REPEAT,
                                     digest, in_calibration, read_extra, read_split, read_spml,
                                     write_jsonl)
except ImportError:
    from prepare_l4_v4_data import (MAX_CHARS, MAX_REPEAT, MINED_REPEAT, SOURCE_REPEAT,
                                    digest, in_calibration, read_extra, read_split, read_spml,
                                    write_jsonl)

V5_REPEAT = {
    ("jailbreakbench/harmful", 1): 2,
    ("jailbreakbench/benign", 0): 2,
    ("in_the_wild/jailbreak", 1): 2,
}
EXTERNAL_CALIB_MODULUS = 5  # hash bucket 0 of 5 -> ~20% calibration slice


def read_jbb(path: Path, label: int) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            text = (record.get("Goal") or "").strip()
            if not text:
                continue
            tag = "harmful" if label == 1 else "benign"
            rows.append({"id": f"jbb-{tag}-{record.get('Index', len(rows))}", "text": text,
                         "label": label, "source": f"jailbreakbench/{tag}"})
    return rows


def read_in_the_wild(paths: list[Path]) -> list[dict]:
    import pyarrow.parquet as pq

    rows = []
    for path in paths:
        table = pq.read_table(path, columns=["prompt", "jailbreak"])
        tag = "jailbreak" if path.name.startswith("jailbreak") else "regular"
        for index, record in enumerate(table.to_pylist()):
            text = (record.get("prompt") or "").strip()
            if not text:
                continue
            rows.append({"id": f"itw-{tag}-{path.stem}-{index}", "text": text,
                         "label": int(bool(record.get("jailbreak"))),
                         "source": f"in_the_wild/{tag}"})
    return rows


def in_external_calib(row_id: str) -> bool:
    return int(hashlib.sha256(f"v5-calib:{row_id}".encode("utf-8")).hexdigest()[:8], 16) \
        % EXTERNAL_CALIB_MODULUS == 0


def hash_sample(rows: list[dict], cap: int) -> list[dict]:
    if len(rows) <= cap:
        return rows
    ordered = sorted(rows, key=lambda row: hashlib.sha256(
        f"v5-sample:{row['id']}".encode("utf-8")).hexdigest())
    return ordered[:cap]


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

    external_calib = [row for row in external if in_external_calib(row["id"])]
    external_test = [row for row in external if not in_external_calib(row["id"])]

    new_rows: list[dict] = []
    jbb_dir = Path(args.jbb_dir) if args.jbb_dir else None
    if jbb_dir and (jbb_dir / "harmful-behaviors.csv").exists():
        new_rows += read_jbb(jbb_dir / "harmful-behaviors.csv", 1)
        new_rows += read_jbb(jbb_dir / "benign-behaviors.csv", 0)
    itw_dir = Path(args.itw_dir) if args.itw_dir else None
    itw_rows: list[dict] = []
    if itw_dir and itw_dir.exists():
        itw_rows = read_in_the_wild(sorted(itw_dir.glob("*.parquet")))
    itw_jailbreak = [row for row in itw_rows if row["label"] == 1]
    itw_regular = hash_sample([row for row in itw_rows if row["label"] == 0], args.max_regular_benign)
    new_rows += itw_jailbreak + itw_regular

    candidates = ([(row, "train") for row in train] + [(row, "dev_mine") for row in dev_mine]
                  + [(row, "v5_new") for row in new_rows])
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
        repeat = V5_REPEAT.get((row["source"], row["label"]),
                               SOURCE_REPEAT.get((row["source"], row["label"]), 1))
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

    def eval_rows(rows: list[dict], with_degree: bool = False) -> list[dict]:
        records = [{"id": r["id"], "payload": r["text"], "label": r["label"], "source": r["source"]}
                   for r in rows]
        if with_degree:
            for record, row in zip(records, rows):
                record["degree"] = row.get("degree")
        return records

    files = {
        "l4_v5_train.jsonl": write_jsonl(out / "l4_v5_train.jsonl", train_rows),
        "l4_v5_calib.jsonl": write_jsonl(out / "l4_v5_calib.jsonl", eval_rows(calib)),
        "l4_v5_test.jsonl": write_jsonl(out / "l4_v5_test.jsonl", eval_rows(test)),
    }
    if external:
        files["l4_v5_external_full.jsonl"] = write_jsonl(
            out / "l4_v5_external_full.jsonl", eval_rows(external, with_degree=True))
        files["l4_v5_external_calib.jsonl"] = write_jsonl(
            out / "l4_v5_external_calib.jsonl", eval_rows(external_calib, with_degree=True))
        files["l4_v5_external_test.jsonl"] = write_jsonl(
            out / "l4_v5_external_test.jsonl", eval_rows(external_test, with_degree=True))

    train_keys = set(merged) - conflicts
    leakage = {
        "train_vs_test": len(train_keys & {digest(r["text"]) for r in test}),
        "train_vs_calib": len(train_keys & {digest(r["text"]) for r in calib}),
        "train_vs_external_full": len(train_keys & {digest(r["text"]) for r in external}),
        "train_vs_external_calib": len(train_keys & {digest(r["text"]) for r in external_calib}),
        "train_vs_external_test": len(train_keys & {digest(r["text"]) for r in external_test}),
    }
    if any(leakage.values()):
        raise SystemExit(f"leakage detected: {leakage}")

    def mix(rows: list[dict]) -> dict:
        return {f"{s}|{l}": n for (s, l), n in
                sorted(Counter((r["source"], r["label"]) for r in rows).items())}

    manifest = {
        "version": args.version,
        "train_rows_unique": len(train_rows),
        "train_rows_after_repeat": sum(row["repeat"] for row in train_rows),
        "train_by_origin": dict(Counter(row["origin"] for row in train_rows)),
        "train_by_source_label": mix(train_rows),
        "truncated_rows": sum(1 for row, _ in candidates if len(row["text"].strip()) > MAX_CHARS),
        "label_conflicts_dropped": len(conflicts),
        "rows_blocked_as_eval_overlap": leaked,
        "calibration_rows": len(calib),
        "test_rows": len(test),
        "external_rows_full": len(external),
        "external_dropped_overlap_or_dup": external_dropped,
        "external_calib_rows": len(external_calib),
        "external_test_rows": len(external_test),
        "external_calib_fraction": round(len(external_calib) / len(external), 4) if external else None,
        "external_calib_by_source_label": mix(external_calib),
        "external_test_by_source_label": mix(external_test),
        "external_full_by_source_label": mix(external),
        "v5_new_sources": {
            "jailbreakbench_rows_added": sum(1 for r in new_rows if r["source"].startswith("jailbreakbench")),
            "in_the_wild_jailbreak_rows": len(itw_jailbreak),
            "in_the_wild_regular_rows_available": sum(1 for r in itw_rows if r["label"] == 0),
            "in_the_wild_regular_rows_sampled": len(itw_regular),
            "max_regular_benign_cap": args.max_regular_benign,
        },
        "mining": mining,
        "leakage_exact_normalized": leakage,
        "external_calib_lock": "sha256('v5-calib:'+id)[:8] % 5 == 0; locked before any v5 training",
        "files_sha256": files,
    }
    (out / "MANIFEST_V5.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--splits-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--version", default="l4-v5-data")
    parser.add_argument("--spml", help="raw/spml/train.jsonl -> external full/calib/test slices")
    parser.add_argument("--jbb-dir", help="raw/jailbreakbench (harmful/benign-behaviors.csv)")
    parser.add_argument("--itw-dir", help="raw/in_the_wild_jailbreaks (*.parquet)")
    parser.add_argument("--max-regular-benign", type=int, default=2000,
                        help="cap on in-the-wild regular (benign) rows added to train; hash-sampled")
    parser.add_argument("--extra", help="extra licensed JSONL {text,label,source} added to train only")
    parser.add_argument("--mine-model", help="existing model.int8.onnx used to mine dev errors (v4)")
    parser.add_argument("--mine-tokenizer", help="existing encoder/ dir")
    parser.add_argument("--mine-threshold", type=float, default=0.65)
    args = parser.parse_args()
    if bool(args.mine_model) != bool(args.mine_tokenizer):
        parser.error("--mine-model and --mine-tokenizer go together")
    if args.max_regular_benign < 0:
        parser.error("--max-regular-benign must be >= 0")
    print(json.dumps(build(args), indent=2))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()