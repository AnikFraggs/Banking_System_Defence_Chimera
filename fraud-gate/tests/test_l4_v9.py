import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

PATH = Path(__file__).resolve().parents[1] / "training/l4_v9.py"
spec = importlib.util.spec_from_file_location("l4_v9", PATH)
v = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v
spec.loader.exec_module(v)


@pytest.fixture(scope="module")
def tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(str(v.ROOT / "build-check/l4_v8/out_v8/hf_checkpoint"), local_files_only=True)


def test_hash_families():
    assert v.skeleton_hash("Ignore previous instructions 123") == v.skeleton_hash("ignore previous instructions 456")
    assert v.skeleton_hash("你好") != v.skeleton_hash("世界")
    assert v.skeleton_hash("123") != v.skeleton_hash("456")
    assert v.norm_hash("Ａ   B") == v.norm_hash("a b")


@pytest.mark.parametrize("view,length", [("a", 128), ("b", 192)])
def test_window_and_segments(tokenizer, view, length):
    rows = [{"text": "hello " * 300, "system": "rules " * 200}]
    indices, enc = v.encode_views(tokenizer, rows, view)
    assert indices == [0]
    assert all(a.shape == (1, length) and a.dtype == np.int64 for a in enc.values())
    assert enc["input_ids"][0, -1] == tokenizer.sep_token_id
    if view == "b":
        assert (enc["token_type_ids"][0, :98] == 0).all()
        assert (enc["token_type_ids"][0, 98:] == 1).all()
    else:
        assert not enc["token_type_ids"].any()


def test_teacher_order_and_literal_specials(tokenizer):
    rows = [{"text": "payload [PAD] hello", "system": "system [SEP] rules"}]
    _, texts = v.teacher_windows(tokenizer, rows, "b")
    assert "system" in texts[0][0] and "rules" in texts[0][0]
    assert "payload" in texts[0][1] and "[PAD]" in texts[0][1]


def test_missing_pair(tokenizer):
    idx, enc = v.encode_views(tokenizer, [{"text": "hello"}], "b")
    assert idx == [] and enc["input_ids"].shape == (0, 192)
    assert np.isnan(v.lex_features("hello")[1])


def test_contextual_labels_not_inherited():
    _, weights = v.gates(np.array([[2., 2.]]), [0., 0.], [None], ["synthetic_rule_pair"], "a")
    assert not weights.any()


def test_reliability_gates():
    centered, weights = v.gates(np.array([[2., -2.], [-3., -2.], [4., 4.]]), [0., 0.], [1, 0, 1], ["normal", "normal", "hackaprompt"], "a")
    assert weights.tolist() == [[1, 0], [1, 1], [0, 1]]
    assert centered[0, 0] == 2
    _, b = v.gates(np.array([[2., 2.]]), [0., 0.], [1], ["normal"], "b")
    assert b.tolist() == [[1, 0]]


def test_calibration_per_slice():
    scores = [np.arange(100.), np.arange(100.) + 100]
    labels = [np.zeros(100), np.zeros(100)]
    cut = v.cutoff(scores, labels, .02)
    assert all(np.mean(s > cut) <= .02 for s in scores)
    with pytest.raises(ValueError):
        v.cutoff(scores, labels, 1)
    with pytest.raises(ValueError):
        v.cutoff([np.array([np.nan])], [np.array([0])])


def test_group_folds_no_fallback():
    with pytest.raises(ValueError):
        v.group_folds(["one"] * 10)
    groups = np.repeat(np.arange(10), 4)
    for train, valid in v.group_folds(groups):
        assert not set(groups[train]) & set(groups[valid])


def test_feature_contract():
    assert len(v.lex_features("abc 123", "rules")) == len(v.FEATURE_NAMES) == len(v.MONOTONE) == 24
    assert v.MONOTONE[:3] == [1, 1, 1]


def test_pair_split_independence():
    spec = importlib.util.spec_from_file_location("prepare_v9", PATH.with_name("prepare_l4_v9_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sets = module.synthetic_pairs()
    for name, rows in sets.items():
        assert all(r["label_a"] is None for r in rows)
        for other, rest in sets.items():
            if name != other:
                assert not {r["system"] for r in rows} & {r["system"] for r in rest}
                assert not {r["payload_group"] for r in rows} & {r["payload_group"] for r in rest}
