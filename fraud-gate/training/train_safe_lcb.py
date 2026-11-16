"""Fit a conservative offline STEP_UP router using Safe-LCB bounds.

The threshold is selected only on training verdicts, then validated on a separate
held-out file. The artifact can tighten STEP_UP threshold/friction only; it never
relaxes high-risk stopping and is never automatically deployed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence

try:
    from .offline_common import (
        ValidationError,
        bounded_identifier,
        canonical_json,
        finite_number,
        read_jsonl,
    )
except ImportError:
    from offline_common import (  # type: ignore
        ValidationError,
        bounded_identifier,
        canonical_json,
        finite_number,
        read_jsonl,
    )

VERDICTS = {"FRAUD", "BENIGN", "INCONCLUSIVE"}
POLICY_SCHEMA = "chimera.safe_lcb.step_up.v1"
MAX_VERDICTS = 100_000
MAX_POLICY_BYTES = 65_536


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson score interval, including finite-sample uncertainty."""
    if isinstance(successes, bool) or isinstance(total, bool):
        raise ValidationError("Wilson counts must be integers")
    if not isinstance(successes, int) or not isinstance(total, int):
        raise ValidationError("Wilson counts must be integers")
    if total < 0 or not 0 <= successes <= total:
        raise ValidationError("Wilson counts require 0 <= successes <= total")
    if not 0.5 < confidence < 1:
        raise ValidationError("confidence must be strictly between 0.5 and 1")
    if total == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return (max(0.0, center - radius), min(1.0, center + radius))


def load_router_verdicts(path: str | Path) -> list[dict[str, Any]]:
    records = read_jsonl(path, max_records=MAX_VERDICTS)
    validated: list[dict[str, Any]] = []
    scenario_ids: set[str] = set()
    for index, record in enumerate(records):
        allowed = {"scenario_id", "group_id", "risk_score", "verdict"}
        required = {"scenario_id", "risk_score", "verdict"}
        if not required <= set(record) or not set(record) <= allowed:
            raise ValidationError(
                f"router verdict[{index}] requires scenario_id/risk_score/verdict and optional group_id"
            )
        scenario = bounded_identifier(record["scenario_id"], "scenario_id")
        if scenario in scenario_ids:
            raise ValidationError(f"duplicate scenario_id: {scenario}")
        scenario_ids.add(scenario)
        verdict = record["verdict"]
        if verdict not in VERDICTS:
            raise ValidationError("router verdict must be FRAUD, BENIGN, or INCONCLUSIVE")
        validated.append({
            "scenario_id": scenario,
            "group_id": bounded_identifier(record.get("group_id", scenario), "group_id"),
            "risk_score": finite_number(record["risk_score"], "risk_score", minimum=0, maximum=1),
            "verdict": verdict,
        })
    return validated


def assert_disjoint_groups(train: Sequence[Mapping[str, Any]], held_out: Sequence[Mapping[str, Any]]) -> None:
    train_groups = {str(row["group_id"]) for row in train}
    held_groups = {str(row["group_id"]) for row in held_out}
    overlap = train_groups & held_groups
    if overlap:
        raise ValidationError(f"train/held-out group leakage: {sorted(overlap)[:5]}")
    train_scenarios = {str(row["scenario_id"]) for row in train}
    held_scenarios = {str(row["scenario_id"]) for row in held_out}
    if train_scenarios & held_scenarios:
        raise ValidationError("scenario_id appears in both train and held-out data")


def router_metrics(
    records: Sequence[Mapping[str, Any]], threshold: float, confidence: float = 0.95
) -> dict[str, Any]:
    threshold = finite_number(threshold, "threshold", minimum=0, maximum=1)
    fraud = [row for row in records if row["verdict"] == "FRAUD"]
    benign = [row for row in records if row["verdict"] == "BENIGN"]
    inconclusive = [row for row in records if row["verdict"] == "INCONCLUSIVE"]
    caught = sum(float(row["risk_score"]) >= threshold for row in fraud)
    challenged = sum(float(row["risk_score"]) >= threshold for row in benign)
    fraud_bounds = wilson_interval(caught, len(fraud), confidence)
    friction_bounds = wilson_interval(challenged, len(benign), confidence)
    return {
        "sample_counts": {
            "total": len(records),
            "fraud": len(fraud),
            "benign": len(benign),
            "inconclusive": len(inconclusive),
        },
        "step_up_counts": {"fraud": caught, "benign": challenged},
        "fraud_recall": {
            "estimate": caught / len(fraud) if fraud else None,
            "lower_bound": fraud_bounds[0],
            "upper_bound": fraud_bounds[1],
        },
        "benign_friction": {
            "estimate": challenged / len(benign) if benign else None,
            "lower_bound": friction_bounds[0],
            "upper_bound": friction_bounds[1],
        },
    }


def _meets_constraints(
    metrics: Mapping[str, Any], min_fraud_recall_lcb: float, max_benign_friction: float
) -> bool:
    if metrics["sample_counts"]["fraud"] == 0 or metrics["sample_counts"]["benign"] == 0:
        return False
    return (
        metrics["fraud_recall"]["lower_bound"] + 1e-12 >= min_fraud_recall_lcb
        and metrics["benign_friction"]["upper_bound"] <= max_benign_friction + 1e-12
    )


def validate_policy_artifact(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "action",
        "step_up_threshold",
        "friction",
        "confidence",
        "constraints",
        "training",
        "held_out",
        "auto_deploy",
        "approval",
    }
    if set(policy) != expected:
        raise ValidationError("Safe-LCB policy has unexpected fields")
    if policy["schema_version"] != POLICY_SCHEMA or policy["action"] != "STEP_UP":
        raise ValidationError("Safe-LCB policy is STEP_UP-only")
    finite_number(policy["step_up_threshold"], "step_up_threshold", minimum=0, maximum=1)
    if policy["auto_deploy"] is not False or policy["approval"] != "HUMAN_REQUIRED":
        raise ValidationError("Safe-LCB policy cannot be automatically deployed")
    friction = policy["friction"]
    if set(friction) != {"maximum_benign_rate", "held_out_upper_bound"}:
        raise ValidationError("friction policy fields are bounded to rate limits")
    finite_number(friction["maximum_benign_rate"], "maximum_benign_rate", minimum=0, maximum=1)
    finite_number(friction["held_out_upper_bound"], "held_out_upper_bound", minimum=0, maximum=1)
    if friction["held_out_upper_bound"] > friction["maximum_benign_rate"] + 1e-12:
        raise ValidationError("held-out friction exceeds its configured bound")


def fit_safe_lcb(
    train: Sequence[Mapping[str, Any]],
    held_out: Sequence[Mapping[str, Any]],
    *,
    min_fraud_recall_lcb: float = 0.8,
    max_benign_friction: float = 0.2,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Select the least-friction safe training threshold; never tune on holdout."""
    min_fraud_recall_lcb = finite_number(
        min_fraud_recall_lcb, "min_fraud_recall_lcb", minimum=0, maximum=1
    )
    max_benign_friction = finite_number(
        max_benign_friction, "max_benign_friction", minimum=0, maximum=1
    )
    if not 0.5 < confidence < 1:
        raise ValidationError("confidence must be strictly between 0.5 and 1")
    assert_disjoint_groups(train, held_out)
    if not train or not held_out:
        raise ValidationError("training and held-out verdicts are both required")

    eligible: list[tuple[float, dict[str, Any]]] = []
    # A fixed grid makes selection reproducible and prevents holdout-driven cutpoints.
    for step in range(101):
        threshold = step / 100
        metrics = router_metrics(train, threshold, confidence)
        if _meets_constraints(metrics, min_fraud_recall_lcb, max_benign_friction):
            eligible.append((threshold, metrics))
    if not eligible:
        raise ValidationError("no STEP_UP threshold satisfies the training Safe-LCB constraints")
    # Higher thresholds produce no more challenges and therefore less friction.
    threshold, training_metrics = max(eligible, key=lambda item: item[0])
    held_metrics = router_metrics(held_out, threshold, confidence)
    if not _meets_constraints(held_metrics, min_fraud_recall_lcb, max_benign_friction):
        raise ValidationError(
            "selected threshold failed held-out Safe-LCB constraints; no policy is emitted"
        )
    policy = {
        "schema_version": POLICY_SCHEMA,
        "action": "STEP_UP",
        "step_up_threshold": threshold,
        "friction": {
            "maximum_benign_rate": max_benign_friction,
            "held_out_upper_bound": held_metrics["benign_friction"]["upper_bound"],
        },
        "confidence": confidence,
        "constraints": {
            "minimum_fraud_recall_lower_bound": min_fraud_recall_lcb,
            "selection": "highest training-qualified threshold; held-out used for validation only",
        },
        "training": training_metrics,
        "held_out": held_metrics,
        "auto_deploy": False,
        "approval": "HUMAN_REQUIRED",
    }
    validate_policy_artifact(policy)
    if len(canonical_json(policy).encode("utf-8")) > MAX_POLICY_BYTES:
        raise ValidationError("Safe-LCB policy artifact exceeds its size bound")
    return policy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-verdicts", required=True)
    parser.add_argument("--held-out-verdicts", required=True)
    parser.add_argument("--authorized-input", action="store_true", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-fraud-recall-lcb", type=float, default=0.8)
    parser.add_argument("--max-benign-friction", type=float, default=0.2)
    parser.add_argument("--confidence", type=float, default=0.95)
    args = parser.parse_args()
    train = load_router_verdicts(args.train_verdicts)
    held_out = load_router_verdicts(args.held_out_verdicts)
    policy = fit_safe_lcb(
        train,
        held_out,
        min_fraud_recall_lcb=args.min_fraud_recall_lcb,
        max_benign_friction=args.max_benign_friction,
        confidence=args.confidence,
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(policy, indent=2, allow_nan=False) + "\n"
    if len(serialized.encode("utf-8")) > MAX_POLICY_BYTES:
        raise ValidationError("Safe-LCB policy output exceeds its size bound")
    destination.write_text(serialized, encoding="utf-8")
    print(json.dumps({
        "output": str(destination),
        "step_up_threshold": policy["step_up_threshold"],
        "held_out_validated": True,
        "auto_deploy": False,
    }, indent=2))


if __name__ == "__main__":
    main()
