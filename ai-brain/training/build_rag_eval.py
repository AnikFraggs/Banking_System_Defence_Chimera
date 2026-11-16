"""Build the labelled triage-retrieval eval set (dev/test) from public sources.

Gold class ids are the ai-brain KNOWLEDGE ids. Sources:
  * PayloadsAllTheThings (MIT, pinned commit) SQLi -> T1190, command injection + XSS -> T1059
  * codesagar/malicious-llm-prompts-v3 + deepset/prompt-injections (local raw copies) malicious -> T1566
  * benign: codesagar/deepset benign rows + unique benign payloads of the CHIMERA layer CSVs
No public labelled text exists locally for T1110 / T1071 / CB-CPN / CB-TL; those classes are only
exercised as false-hit targets. Split is a stable hash of the normalized text (40% dev / 60% test).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "datasets/new_custom_datasets/raw"
PATT_DIR = RAW / "rag_eval/patt"
OUT_DIR = ROOT / "datasets/new_custom_datasets/out/rag_eval"
REPO = "swisskyrepo/PayloadsAllTheThings"

PATT_FILES = {
    "T1190": ["SQL Injection/Intruder/" + n for n in (
        "Auth_Bypass.txt", "Auth_Bypass2.txt", "Generic_ErrorBased.txt", "Generic_TimeBased.txt",
        "Generic_UnionSelect.txt", "SQLi_Polyglots.txt", "FUZZDB_MSSQL.txt", "FUZZDB_Oracle.txt",
        "FUZZDB_MySQL-WHERE_Time.txt", "FUZZDB_Postgres_Enumeration.txt",
        "payloads-sql-blind-MySQL-WHERE")],
    "T1059": ["Command Injection/Intruder/command-execution-unix.txt",
              "Command Injection/Intruder/command_exec.txt"]
             + ["XSS Injection/Intruders/" + n for n in (
                 "RSNAKE_XSS.txt", "XSS_Polyglots.txt", "xss_payloads_quick.txt",
                 "BRUTELOGIC-XSS-STRINGS.txt", "JHADDIX_XSS.txt", "0xcela_event_handlers.txt")],
}
PER_FILE_CAP = 150
BENIGN_ULTRACHAT_CAP = 1500


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def split_of(text: str) -> str:
    return "dev" if int(hashlib.sha256(norm(text).encode()).hexdigest(), 16) % 10 < 4 else "test"


def fetch_patt() -> dict:
    PATT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = PATT_DIR / "MANIFEST.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    with urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/commits/master", timeout=30) as r:
        commit = json.load(r)["sha"]
    files = []
    for paths in PATT_FILES.values():
        for path in paths:
            url = f"https://raw.githubusercontent.com/{REPO}/{commit}/{urllib.request.quote(path)}"
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
            local = PATT_DIR / path.replace("/", "__")
            local.write_bytes(data)
            files.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"repo": REPO, "license": "MIT", "commit": commit, "files": files}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def patt_rows(rng: random.Random) -> list[dict]:
    rows = []
    for gold, paths in PATT_FILES.items():
        for path in paths:
            lines = (PATT_DIR / path.replace("/", "__")).read_text(encoding="utf-8", errors="replace").splitlines()
            lines = sorted({ln.strip() for ln in lines if 4 <= len(ln.strip()) <= 600 and not ln.startswith("#")})
            rng.shuffle(lines)
            rows += [{"text": t, "gold": [gold], "source": "patt:" + path.split("/")[-1]} for t in lines[:PER_FILE_CAP]]
    return rows


def prompt_rows(rng: random.Random) -> list[dict]:
    import pandas as pd

    rows, ultrachat = [], []
    for name in ("train.jsonl", "test.jsonl"):
        for line in (RAW / "codesagar_v3" / name).open(encoding="utf-8"):
            r = json.loads(line)
            text = r["prompt"][:2000]
            if r["malicious"]:
                rows.append({"text": text, "gold": ["T1566"], "source": "codesagar:" + r["source"]})
            elif r["source"] == "HuggingFaceH4/ultrachat_200k":
                ultrachat.append({"text": text, "gold": [], "source": "codesagar:ultrachat"})
            else:
                rows.append({"text": text, "gold": [], "source": "codesagar:" + r["source"]})
    rng.shuffle(ultrachat)
    rows += ultrachat[:BENIGN_ULTRACHAT_CAP]
    for name in ("train.parquet", "test.parquet"):
        for text, label in pd.read_parquet(RAW / "v7/deepset" / name)[["text", "label"]].itertuples(index=False):
            rows.append({"text": text[:2000], "gold": ["T1566"] if label == 1 else [], "source": "deepset"})
    return rows


def layer_benign_rows() -> list[dict]:
    rows = []
    for f in sorted((ROOT / "datasets").glob("layer*.csv")):
        with f.open(newline="", encoding="utf-8") as h:
            payloads = {r["payload"] for r in csv.DictReader(h) if r["label"] == "0" and r["payload"].strip()}
        rows += [{"text": p, "gold": [], "source": "chimera:" + f.stem} for p in sorted(payloads)]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--authorized-data", action="store_true", required=True)
    ap.add_argument("--seed", type=int, default=20261115)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    manifest = fetch_patt()

    seen, rows, dropped = set(), [], 0
    for row in patt_rows(rng) + prompt_rows(rng) + layer_benign_rows():
        key = norm(row["text"])
        if not key or key in seen:
            dropped += 1
            continue
        seen.add(key)
        row["split"] = split_of(row["text"])
        rows.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "rag_eval.jsonl"
    with out.open("w", encoding="utf-8") as h:
        for row in rows:
            h.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts: dict = {}
    for row in rows:
        k = f"{row['split']}|{row['gold'][0] if row['gold'] else 'benign'}"
        counts[k] = counts.get(k, 0) + 1
    report = {"rows": len(rows), "duplicates_dropped": dropped, "counts": dict(sorted(counts.items())),
              "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "patt_commit": manifest["commit"],
              "licences": {"PayloadsAllTheThings": "MIT", "deepset/prompt-injections": "Apache-2.0",
                           "codesagar/malicious-llm-prompts-v3": "not stated on the page",
                           "CHIMERA layer CSVs": "project-internal"},
              "uncovered_classes": ["T1110", "T1071", "CB-CPN", "CB-TL"]}
    (OUT_DIR / "MANIFEST.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    json.dump(report, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
