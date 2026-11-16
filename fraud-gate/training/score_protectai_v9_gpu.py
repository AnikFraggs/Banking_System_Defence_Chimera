from __future__ import annotations

import json

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from l4_v9 import OUT, ROOT, read_rows

BASE = ROOT / "datasets/new_custom_datasets/out/v5"
PDIR = ROOT / "fraud-gate/training/benchmarks/rivals/protectai_deberta_v3"


def spml_systems():
    raw = ROOT / "datasets/new_custom_datasets/raw/spml/train.jsonl"
    out = []
    with raw.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                out.append(json.loads(line).get("System Prompt") or None)
    return out


def attach(rows, systems):
    res = []
    for r in rows:
        r = dict(r)
        rid = r.get("id", "")
        if isinstance(rid, str) and rid.startswith("spml-"):
            idx = int(rid.split("-")[1])
            if idx < len(systems):
                r["system"] = systems[idx]
        res.append(r)
    return res


def main():
    systems = spml_systems()
    cal = {"internal": list(read_rows(BASE / "l4_v5_calib.jsonl")),
           "external": attach(list(read_rows(BASE / "l4_v5_external_calib.jsonl")), systems),
           "v8new": list(read_rows(ROOT / "build-check/l4_v8/new_calib.jsonl")),
           "v9new": list(read_rows(OUT / "new_calib.jsonl")),
           "paired": list(read_rows(OUT / "paired_calib.jsonl"))}
    test = {"internal": list(read_rows(BASE / "l4_v5_test.jsonl")),
            "external": attach(list(read_rows(BASE / "l4_v5_external_test.jsonl")), systems),
            "v8new": list(read_rows(ROOT / "build-check/l4_v8/new_test.jsonl")),
            "v9new": list(read_rows(OUT / "new_test.jsonl")),
            "paired": list(read_rows(OUT / "paired_test.jsonl"))}
    all_rows = {**{f"cal_{k}": v for k, v in cal.items()}, **{f"test_{k}": v for k, v in test.items()}}
    tok = AutoTokenizer.from_pretrained(str(PDIR), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(PDIR), local_files_only=True).cuda().eval()
    cache = {}

    def run(texts, pairs=None):
        out = np.full(len(texts), np.nan, np.float32)
        with torch.inference_mode():
            for s in range(0, len(texts), 32):
                if pairs is None:
                    enc = tok(texts[s:s + 32], padding=True, truncation=True, max_length=512, return_tensors="np")
                else:
                    enc = tok([p[0] for p in pairs[s:s + 32]], [p[1] for p in pairs[s:s + 32]], padding=True, truncation=True, max_length=512, return_tensors="np")
                enc.pop("token_type_ids", None)
                feed = {k: torch.from_numpy(v).cuda() for k, v in enc.items()}
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    lg = model(**feed).logits.float()
                out[s:s + len(lg)] = (lg[:, 1] - lg[:, 0]).cpu().numpy()
        return out

    for key, rows in all_rows.items():
        texts = [r["text"][:8192] for r in rows]
        ma = run(texts)
        bidx = [i for i, r in enumerate(rows) if r.get("system")]
        mb = np.full(len(rows), np.nan, np.float32)
        if bidx:
            pairs = [(rows[i]["system"][:8192], rows[i]["text"][:8192]) for i in bidx]
            mb[bidx] = run([rows[i]["text"][:8192] for i in bidx], pairs)
        cache[f"{key}|a"], cache[f"{key}|b"] = ma, mb
        np.savez_compressed(OUT / "protectai_margins.npz", **cache)
        print(f"protectai {key} n={len(rows)} b={len(bidx)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
