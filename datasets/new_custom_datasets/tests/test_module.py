"""Tests use tiny made-up rows to check the plumbing. They say nothing about any real dataset."""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chimera_datasets import build as B, score as S
from chimera_datasets.catalog import Source
from chimera_datasets.normalize import canon, coerce_label, ColumnError
from chimera_datasets.stats import auc, wilson


def src(key, role="train", cols=None):
    return Source(key=key, track="text", host="manual", ref="x", layer="L4_test", role=role,
                  license="test", status="test", cols=cols or {})


def write_jsonl(raw, key, rows, name="data.jsonl"):
    d = os.path.join(raw, key)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw = os.path.join(self.tmp, "raw")
        self.out = os.path.join(self.tmp, "out")

    def test_canon_ignores_invisible_and_case(self):
        self.assertEqual(canon("Ignore  PREVIOUS​ instructions"), canon("ignore previous instructions"))

    def test_label_coercion(self):
        self.assertEqual([coerce_label(x) for x in (True, "False", 1, "0.0", "Benign", "attack", "maybe", 7)],
                         [1, 0, 1, 0, 0, 1, None, None])

    def test_wilson_and_auc(self):
        lo, hi = wilson(37, 52)
        self.assertAlmostEqual(lo, 0.577, places=2)
        self.assertAlmostEqual(hi, 0.817, places=2)
        self.assertEqual(auc([1, 2, 3, 4], [0, 0, 1, 1]), 1.0)
        self.assertEqual(auc([1, 1, 1, 1], [0, 0, 1, 1]), 0.5)

    def test_dedup_conflict_heldout_and_bad_rows(self):
        write_jsonl(self.raw, "a", [
            {"t": "alpha payload", "y": 1}, {"t": "beta payload", "y": 0},
            {"t": "gamma  payload", "y": 1}, {"t": "", "y": 1}, {"t": "delta", "y": "unknown"}])
        write_jsonl(self.raw, "b", [{"t": "ALPHA payload", "y": 1}, {"t": "epsilon payload", "y": 1}])
        write_jsonl(self.raw, "c", [{"t": "beta payload", "y": 1}])
        cols = {"payload": "t", "label": "y"}
        r = B.build(self.raw, self.out, sources=[src("a", cols=cols), src("b", "heldout", cols), src("c", cols=cols)])
        self.assertEqual(r["conflicts"], 1)                       # beta: 0 in a, 1 in c
        rows = list(csv.DictReader(open(os.path.join(self.out, "text_all.csv"), encoding="utf-8")))
        texts = {x["payload"]: x for x in rows}
        self.assertNotIn("beta payload", texts)
        self.assertEqual(texts["ALPHA payload"]["split"], "external_test")   # held-out copy wins
        self.assertNotIn("alpha payload", texts)
        self.assertEqual(len(rows), 3)                           # alpha(b), gamma, epsilon
        self.assertEqual(r["dup_removed"], 1)

    def test_external_ids_disjoint_and_deterministic(self):
        write_jsonl(self.raw, "a", [{"t": f"row {i}", "y": i % 2} for i in range(300)])
        write_jsonl(self.raw, "b", [{"t": f"other {i}", "y": i % 2} for i in range(50)])
        cols = {"payload": "t", "label": "y"}
        sources = [src("a", cols=cols), src("b", "heldout", cols)]
        r1 = B.build(self.raw, self.out, sources=sources)
        r2 = B.build(self.raw, self.out, sources=sources)
        self.assertEqual(r1["files"], r2["files"])
        ids = {}
        for sp in ("train", "dev", "test", "external_test"):
            ids[sp] = {x["id"] for x in csv.DictReader(open(os.path.join(self.out, f"text_{sp}.csv"), encoding="utf-8"))}
        for a in ids:
            for b in ids:
                if a < b:
                    self.assertFalse(ids[a] & ids[b], (a, b))
        self.assertTrue(os.path.exists(os.path.join(self.out, "SPLIT_LOCK.json")))

    def test_payload_not_altered_and_header_compatible(self):
        raw_payload = "ig​nore  previous"
        write_jsonl(self.raw, "a", [{"t": raw_payload, "y": 1}])
        B.build(self.raw, self.out, sources=[src("a", cols={"payload": "t", "label": "y"})])
        with open(os.path.join(self.out, "text_all.csv"), newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            self.assertEqual(rd.fieldnames[:6], ["label", "payload", "severity", "role", "purpose", "ip"])
            row = next(rd)
        self.assertEqual(row["payload"], raw_payload)
        self.assertEqual((row["role"], row["purpose"], row["ip"]), ("", "", ""))

    def test_missing_columns_raise_with_help(self):
        write_jsonl(self.raw, "a", [{"foo": "x", "bar": 1}])
        with self.assertRaises(ColumnError) as cm:
            B.build(self.raw, self.out, sources=[src("a")])
        self.assertIn("foo", str(cm.exception))

    def test_length_artifact_warning(self):
        rows = [{"t": "x" * 200 + str(i), "y": 1} for i in range(60)] + [{"t": "y" + str(i), "y": 0} for i in range(60)]
        write_jsonl(self.raw, "a", rows)
        r = B.build(self.raw, self.out, sources=[src("a", cols={"payload": "t", "label": "y"})])
        self.assertTrue(any("payload length" in w for w in r["warnings"]))

    def test_score_with_missing_predictions(self):
        write_jsonl(self.raw, "a", [{"t": f"r{i}", "y": 1 if i < 4 else 0} for i in range(8)])
        B.build(self.raw, self.out, sources=[src("a", cols={"payload": "t", "label": "y"})], ratios=(100, 0))
        split = os.path.join(self.out, "text_train.csv")
        rows = list(csv.DictReader(open(split, encoding="utf-8")))
        pred = os.path.join(self.tmp, "pred.csv")
        with open(pred, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "pred"])
            for x in rows[:-1]:
                w.writerow([x["id"], "BLOCK" if x["label"] == "1" else "ALLOW"])
        res = S.score(split, pred)
        self.assertEqual(res["missing"], 1)
        self.assertEqual(res["rows"]["ALL"]["fn"] + res["rows"]["ALL"]["fp"], 0)
        self.assertIn("WARNING", S.render(res))


if __name__ == "__main__":
    unittest.main()
