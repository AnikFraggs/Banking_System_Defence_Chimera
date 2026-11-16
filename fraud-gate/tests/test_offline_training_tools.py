from __future__ import annotations

import copy
import json
import math

import pytest

from training.hard_negative_synthesis import (
    FEATURES,
    LABEL,
    MAX_RECORDS,
    load_authorized_csv,
    load_hard_negatives,
    split_by_group,
    synthesize_deterministic,
    validate_hard_negative,
)
from training.offline_common import ValidationError, strict_json_loads
from training.train_contrastive import canonical_key_value, combine_pairs
from training.train_creditcard_hgb_synthetic import RUNTIME_FEATURES, synthetic_to_frame
from training.train_lora_verdicts import prepare_verdicts
from training.train_safe_lcb import (
    fit_safe_lcb,
    router_metrics,
    validate_policy_artifact,
    wilson_interval,
)


def source_rows(count: int = 4):
    return [
        {
            "Time": float(index),
            "Class": float(index % 2),
            "Amount": 1.0 + index,
            **{name: (index + 1) * 0.01 for name in FEATURES},
        }
        for index in range(count)
    ]


def verdict_row(index: int, score: float, verdict: str, prefix: str = "row"):
    return {
        "scenario_id": f"{prefix}-{index}",
        "group_id": f"{prefix}-group-{index}",
        "risk_score": score,
        "verdict": verdict,
    }


def analyst_row(verdict: str = "FRAUD"):
    return {
        "scenario_id": "sim-case-1",
        "telemetry": {"payload": "simulator", "amount": 2.5},
        "verdict": verdict,
        "rationale": "Repeated low-value attempts in the simulator.",
        "evidence": ["slow inter-event gaps"],
    }


def test_strict_json_rejects_duplicates_and_non_finite_values():
    with pytest.raises(ValidationError, match="duplicate JSON key"):
        strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(ValidationError, match="non-finite"):
        strict_json_loads('{"a":NaN}')


def test_authorized_source_is_explicit_and_sensitive_columns_are_rejected(tmp_path):
    path = tmp_path / "simulator.csv"
    path.write_text(
        "Time,Class,Amount,card_number," + ",".join(FEATURES) + "\n"
        + "0,1,1.0,4111111111111111," + ",".join("0" for _ in FEATURES) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="authorized-input"):
        load_authorized_csv(path)
    with pytest.raises(ValidationError, match="forbidden"):
        load_authorized_csv(path, simulator=True)


def test_deterministic_synthesis_has_bounded_synthetic_schema_and_stable_seed():
    first = synthesize_deterministic(source_rows(), count=30, seed=19, held_out_fraction=0.25)
    second = synthesize_deterministic(source_rows(), count=30, seed=19, held_out_fraction=0.25)
    assert first == second
    assert len(first) == 30
    assert {first_record["label"] for first_record in first} == {LABEL}
    assert {record["split"] for record in first} == {"TRAIN", "HELD_OUT"}
    for record in first:
        validate_hard_negative(record)
        offsets = [event["offset_ms"] for event in record["events"]]
        assert offsets == sorted(set(offsets))
        assert len(offsets) >= 3
        assert record["log_amount"] == pytest.approx(math.log(record["Amount"]))
        assert not ({"card_number", "account_id", "cvv"} & set(record))


def test_synthesis_rejects_invalid_ranges_and_maximum_counts():
    with pytest.raises(ValidationError, match="count"):
        synthesize_deterministic(source_rows(), count=MAX_RECORDS + 1)
    record = synthesize_deterministic(source_rows(), count=1)[0]
    invalid = copy.deepcopy(record)
    invalid["card_features"]["V1"] = 1000
    with pytest.raises(ValidationError, match="V1"):
        validate_hard_negative(invalid)
    invalid = copy.deepcopy(record)
    invalid["order_memo"] = "card 4111 1111 1111 1111"
    with pytest.raises(ValidationError, match="possible"):
        validate_hard_negative(invalid)
    invalid = copy.deepcopy(record)
    invalid["unexpected"] = "not allowed"
    with pytest.raises(ValidationError, match="keys mismatch"):
        validate_hard_negative(invalid)


def test_group_split_prevents_near_duplicate_leakage_and_deduplicates(tmp_path):
    records = synthesize_deterministic(source_rows(), count=50, seed=7, held_out_fraction=0.3)
    train_groups = {r["group_id"] for r in records if r["split"] == "TRAIN"}
    held_groups = {r["group_id"] for r in records if r["split"] == "HELD_OUT"}
    assert train_groups and held_groups and train_groups.isdisjoint(held_groups)

    reassigned = split_by_group(records, held_out_fraction=0.3, seed=7)
    assert {(r["record_id"], r["split"]) for r in reassigned} == {
        (r["record_id"], r["split"]) for r in records
    }

    duplicate_path = tmp_path / "duplicates.jsonl"
    duplicate_path.write_text(
        json.dumps(records[0]) + "\n" + json.dumps(records[0]) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="duplicate"):
        load_hard_negatives(duplicate_path)


def test_hgb_projection_uses_runtime_contract_not_log_amount():
    records = synthesize_deterministic(source_rows(), count=6, seed=2)
    frame = synthetic_to_frame(records, "TRAIN")
    assert list(frame.columns) == ["Time", *RUNTIME_FEATURES, "Class", "group_id"]
    assert "log_amount" not in frame
    assert set(frame["Class"]) == {1}


def test_canonical_telemetry_is_order_independent_and_escaped():
    left = {"z": [1, True, None], "a": {"text": "x=y\n", "n": 0.5}}
    right = {"a": {"n": 0.5, "text": "x=y\n"}, "z": [1, True, None]}
    assert canonical_key_value(left) == canonical_key_value(right)
    assert 'a.text="x=y\\n"' in canonical_key_value(left)
    assert len(combine_pairs(
        [{"scenario_id": "a", "anchor": "a", "positive": "p"}],
        [{"scenario_id": "a", "anchor": "a", "positive": "p"}],
    )) == 1


def test_lora_targets_are_structured_and_settlement_free():
    prepared = prepare_verdicts([analyst_row()])
    target = json.loads(prepared[0]["target"])
    assert target == {
        "verdict": "FRAUD",
        "rationale": "Repeated low-value attempts in the simulator.",
        "evidence": ["slow inter-event gaps"],
    }
    assert set(target).isdisjoint({"action", "capture", "void", "refund", "settlement"})
    with pytest.raises(ValidationError, match="verdict"):
        prepare_verdicts([analyst_row("LIKELY_FRAUD")])
    action_row = analyst_row()
    action_row["rationale"] = "Capture the payment immediately."
    with pytest.raises(ValidationError, match="settlement"):
        prepare_verdicts([action_row])


def test_wilson_bounds_cover_observed_rate_and_handle_empty_sample():
    lower, upper = wilson_interval(5, 10, confidence=0.95)
    assert 0 <= lower < 0.5 < upper <= 1
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValidationError):
        wilson_interval(11, 10)


def test_safe_lcb_selects_on_train_and_emits_only_bounded_step_up_policy():
    train = [verdict_row(i, 0.9 if i < 18 else 0.1, "FRAUD") for i in range(20)]
    train += [verdict_row(i + 20, 0.05, "BENIGN") for i in range(20)]
    held = [verdict_row(i, 0.9 if i < 18 else 0.1, "FRAUD", "held") for i in range(20)]
    held += [verdict_row(i + 20, 0.05, "BENIGN", "held") for i in range(20)]
    policy = fit_safe_lcb(
        train, held, min_fraud_recall_lcb=0.5, max_benign_friction=0.2, confidence=0.95
    )
    validate_policy_artifact(policy)
    assert policy["action"] == "STEP_UP"
    assert policy["step_up_threshold"] == 0.9
    assert policy["auto_deploy"] is False
    assert policy["training"]["sample_counts"]["total"] == 40
    assert policy["held_out"]["fraud_recall"]["lower_bound"] >= 0.5
    assert policy["held_out"]["benign_friction"]["upper_bound"] <= 0.2
    assert "VOID" not in json.dumps(policy)


def test_safe_lcb_rejects_group_leakage_and_failed_holdout_without_artifact():
    train = [verdict_row(i, 0.9, "FRAUD") for i in range(20)]
    train += [verdict_row(i + 20, 0.1, "BENIGN") for i in range(20)]
    leaked = [dict(row) for row in train]
    with pytest.raises(ValidationError, match="leakage|both"):
        fit_safe_lcb(train, leaked, min_fraud_recall_lcb=0, max_benign_friction=1)

    held = [verdict_row(i, 0.0, "FRAUD", "hold") for i in range(20)]
    held += [verdict_row(i + 20, 0.1, "BENIGN", "hold") for i in range(20)]
    with pytest.raises(ValidationError, match="held-out"):
        fit_safe_lcb(train, held, min_fraud_recall_lcb=0.8, max_benign_friction=0.5)


def test_router_metrics_include_all_analyst_verdict_counts():
    rows = [
        verdict_row(0, 0.9, "FRAUD"),
        verdict_row(1, 0.1, "BENIGN"),
        verdict_row(2, 0.5, "INCONCLUSIVE"),
    ]
    metrics = router_metrics(rows, 0.8)
    assert metrics["sample_counts"] == {"total": 3, "fraud": 1, "benign": 1, "inconclusive": 1}
