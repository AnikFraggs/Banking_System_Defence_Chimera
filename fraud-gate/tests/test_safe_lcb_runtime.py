from __future__ import annotations

import json

import pytest

from app.safe_lcb import SafeLcbError, apply_step_up, load_safe_lcb
from app.schemas import Action


def _policy(tmp_path, **changes):
    artifact = {
        "schema_version": "chimera.safe_lcb.step_up.v1",
        "action": "STEP_UP",
        "step_up_threshold": 0.3,
        "friction": {"maximum_benign_rate": 0.2, "held_out_upper_bound": 0.1},
        "confidence": 0.95,
        "constraints": {"minimum_fraud_recall_lower_bound": 0.8},
        "auto_deploy": False,
        "approval": "HUMAN_REQUIRED",
    }
    artifact.update(changes)
    path = tmp_path / "safe_lcb.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_step_up_only_escalates_capture_and_never_touches_void(tmp_path):
    policy = load_safe_lcb(_policy(tmp_path))

    action, reason = apply_step_up(Action.CAPTURE, 0.4, policy)
    assert action is Action.CHALLENGE
    assert reason is not None and reason.code == "SAFE_LCB_STEP_UP"

    # Below threshold, no friction is added.
    assert apply_step_up(Action.CAPTURE, 0.1, policy)[0] is Action.CAPTURE

    # VOID is a hard stop and can never be downgraded.
    assert apply_step_up(Action.VOID, 0.99, policy)[0] is Action.VOID
    # An existing CHALLENGE is never converted back to CAPTURE.
    assert apply_step_up(Action.CHALLENGE, 0.05, policy)[0] is Action.CHALLENGE


def test_safe_lcb_rejects_non_step_up_and_auto_deploy(tmp_path):
    with pytest.raises(SafeLcbError, match="STEP_UP"):
        load_safe_lcb(_policy(tmp_path, action="VOID"))
    with pytest.raises(SafeLcbError, match="auto-deploy"):
        load_safe_lcb(_policy(tmp_path, auto_deploy=True))
