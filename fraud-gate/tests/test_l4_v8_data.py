from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from training.prepare_l4_v8_data import fingerprint, group_key, offer, split_for


def test_prefix_groups_ignore_number_and_whitespace_variations():
    first = group_key("PLEASE   review account 123 " + "example " * 30)
    second = group_key("please review account 987 " + "example " * 30)
    assert first == second
    assert split_for(first) == split_for(second)
    assert fingerprint(" A\u2028B ") == fingerprint("a b")


def test_bounded_selection_is_independent_of_input_order():
    rows = [{"text": str(i)} for i in range(50)]
    a, b = [], []
    for row in rows:
        offer(a, row, 4)
    for row in reversed(rows):
        offer(b, row, 4)
    assert sorted(x[1] for x in a) == sorted(x[1] for x in b)
    assert len(a) == 4


def test_distillation_loader_reads_payload_and_unicode_jsonl(tmp_path):
    trainer = Path(__file__).resolve().parents[2] / "build-check/l4_claude/distill_l4.py"
    if not trainer.exists():
        import pytest
        pytest.skip("local distillation helper is outside the service image")
    spec = importlib.util.spec_from_file_location("distill_helper", trainer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({"payload": "first\u2028second", "label": 1}, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = list(module.read_rows(path))
    assert len(rows) == 1
    assert rows[0]["text"] == "first\u2028second"
    assert rows[0]["label"] == 1
