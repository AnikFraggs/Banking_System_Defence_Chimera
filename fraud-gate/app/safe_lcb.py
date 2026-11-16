"""Runtime Safe-LCB STEP_UP policy: tightening friction only, never weakening."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import Action, Reason

STEP_UP_SCHEMA = "chimera.safe_lcb.step_up.v1"


class SafeLcbError(ValueError):
    """A Safe-LCB artifact cannot be applied at runtime."""


@dataclass(frozen=True)
class SafeLcbPolicy:
    step_up_threshold: float
    maximum_benign_rate: float
    confidence: float
    minimum_fraud_recall_lcb: float


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SafeLcbError(f"{name} must be numeric")
    number = float(value)
    if number != number or not minimum <= number <= maximum:
        raise SafeLcbError(f"{name} must be finite and in [{minimum}, {maximum}]")
    return number


def load_safe_lcb(path: str | Path) -> SafeLcbPolicy:
    source = Path(path)
    if not source.is_file():
        raise SafeLcbError(f"Safe-LCB policy artifact not found: {source}")
    try:
        artifact = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SafeLcbError("Safe-LCB policy artifact is not valid JSON") from exc
    if not isinstance(artifact, dict):
        raise SafeLcbError("Safe-LCB policy artifact must be an object")
    if artifact.get("schema_version") != STEP_UP_SCHEMA or artifact.get("action") != "STEP_UP":
        raise SafeLcbError("only STEP_UP Safe-LCB policies are accepted")
    if artifact.get("auto_deploy") is not False or artifact.get("approval") != "HUMAN_REQUIRED":
        raise SafeLcbError("Safe-LCB policy requires human approval and no auto-deploy")
    friction = artifact.get("friction")
    if not isinstance(friction, dict):
        raise SafeLcbError("Safe-LCB policy is missing its friction block")
    constraints = artifact.get("constraints")
    if not isinstance(constraints, dict):
        raise SafeLcbError("Safe-LCB policy is missing its constraints block")
    return SafeLcbPolicy(
        step_up_threshold=_number(artifact["step_up_threshold"], "step_up_threshold", 0, 1),
        maximum_benign_rate=_number(friction.get("maximum_benign_rate"), "maximum_benign_rate", 0, 1),
        confidence=_number(artifact.get("confidence"), "confidence", 0.5, 1),
        minimum_fraud_recall_lcb=_number(
            constraints.get("minimum_fraud_recall_lower_bound"),
            "minimum_fraud_recall_lower_bound",
            0,
            1,
        ),
    )


def apply_step_up(
    action: Action, score: float, policy: SafeLcbPolicy
) -> tuple[Action, Reason | None]:
    """Escalate CAPTURE to CHALLENGE above the trained threshold.

    A STEP_UP policy can only add friction. It never downgrades VOID, never
    converts a CHALLENGE into a CAPTURE, and never raises a score.
    """
    if action is Action.VOID:
        return action, None
    if action is Action.CAPTURE and score >= policy.step_up_threshold:
        return Action.CHALLENGE, Reason(
            code="SAFE_LCB_STEP_UP",
            message=(
                "Safe-LCB step-up threshold requires additional friction before capture; "
                "held-out Wilson bounds validated offline."
            ),
            component="safe_lcb",
            score=round(score, 6),
        )
    return action, None
