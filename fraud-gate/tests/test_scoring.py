from __future__ import annotations

import pytest

from app.card_model import CardModel
from app.schemas import ScoreRequest
from app.scoring import feature_hash, score_request


def test_deterministic_high_card_score_reason_and_hash(make_payload, fake_model):
    fake_model.model.probability = 0.91
    request = ScoreRequest(**make_payload())

    first = score_request(request, fake_model)
    second = score_request(request, fake_model)

    assert first.score == second.score == 0.91
    assert first.action == second.action == "VOID"
    assert first.fallback is False
    assert [reason.code for reason in first.reasons] == ["CARD_MODEL_HIGH"]
    assert feature_hash(request, first.model_version) == feature_hash(request, second.model_version)


def test_feature_order_comes_from_artifact_not_json_order(make_payload, fake_model, fake_estimator):
    request = ScoreRequest(**make_payload(card_features={"V2": 2.0, "V1": 1.0}))
    score_request(request, fake_model)
    assert fake_estimator.last_vector == [1.0, 2.0]


def test_missing_model_fails_closed(make_payload):
    result = score_request(ScoreRequest(**make_payload()), None)
    assert result.action == "CHALLENGE"
    assert result.fallback is True
    assert result.model_version == "unavailable"
    assert result.reasons[0].code == "MODEL_UNAVAILABLE"


@pytest.mark.parametrize(
    "features",
    [None, {"V1": 1.0}, {"V1": 1.0, "V2": 2.0, "V3": 3.0}],
)
def test_missing_or_mismatched_features_fail_closed(make_payload, fake_model, features):
    result = score_request(
        ScoreRequest(**make_payload(card_features=features)), fake_model
    )
    assert result.action == "CHALLENGE"
    assert result.fallback is True
    assert [reason.code for reason in result.reasons] == ["INVALID_FEATURES"]


def test_scoring_exception_fails_closed(make_payload):
    class BrokenModel:
        classes_ = [0, 1]

        def predict_proba(self, _matrix):
            raise RuntimeError("synthetic inference failure")

    model = CardModel(BrokenModel(), ("V1", "V2"), "broken-v1", 0.5)
    result = score_request(ScoreRequest(**make_payload()), model)
    assert result.action == "CHALLENGE"
    assert result.fallback is True
    assert result.reasons[0].code == "MODEL_UNAVAILABLE"


def test_quick_recheck_skips_evidence_analysis_and_uses_prior(
    make_payload, fake_model, monkeypatch
):
    def unexpected_analysis(_evidence):
        raise AssertionError("QUICK_RECHECK must skip evidence/OCR analysis")

    monkeypatch.setattr("app.scoring.score_evidence", unexpected_analysis)
    request = ScoreRequest(**make_payload(
        mode="QUICK_RECHECK",
        evidence={"generator_marker": "stable diffusion"},
        context={"prior_evidence_score": 0.2},
    ))
    result = score_request(request, fake_model)
    assert result.component_scores["evidence"] == 0.2
    assert result.action == "CAPTURE"
    assert not any(reason.code == "EVIDENCE_ARTIFACT" for reason in result.reasons)


def test_quick_recheck_prior_evidence_is_still_enforced(make_payload, fake_model):
    request = ScoreRequest(**make_payload(
        mode="QUICK_RECHECK",
        context={"prior_evidence_score": 0.9},
    ))
    result = score_request(request, fake_model)
    assert result.component_scores["evidence"] == 0.9
    assert result.action == "VOID"
    assert any(reason.code == "EVIDENCE_ARTIFACT" for reason in result.reasons)


def test_strong_device_burst_has_stable_reason_and_voids(make_payload, fake_model):
    history = [
        {
            "device_id": "device-a",
            "destination": f"merchant-{index}",
            "amount": "5.00",
            "timestamp": f"2026-01-01T11:5{index}:00Z",
        }
        for index in range(8)
    ]
    result = score_request(ScoreRequest(**make_payload(history=history)), fake_model)
    assert result.component_scores["device_velocity"] == 1.0
    assert result.action == "VOID"
    assert any(reason.code == "DEVICE_BURST" for reason in result.reasons)


def test_strong_automation_has_stable_reason_and_at_least_challenges(make_payload, fake_model):
    request = ScoreRequest(**make_payload(
        telemetry={"keystroke_intervals_ms": [100.0] * 12, "mouse_movements": []}
    ))
    result = score_request(request, fake_model)
    assert result.component_scores["biometrics"] == 1.0
    assert result.action in {"CHALLENGE", "VOID"}
    assert any(reason.code == "AUTOMATION_PATTERN" for reason in result.reasons)


def test_medium_automation_requires_step_up_instead_of_void(make_payload, fake_model):
    request = ScoreRequest(**make_payload(
        telemetry={
            "keystroke_intervals_ms": [110.0, 114.0, 116.0, 118.0, 122.0, 124.0, 126.0, 130.0],
            "mouse_movements": [],
        }
    ))
    result = score_request(request, fake_model)
    assert 0.35 <= result.component_scores["biometrics"] < 0.85
    assert result.action == "CHALLENGE"


def test_medium_evidence_requires_review_instead_of_void(make_payload, fake_model):
    request = ScoreRequest(**make_payload(
        evidence={"generator_marker": "synthetic-generation-marker", "pixel_residual": 0.72}
    ))
    result = score_request(request, fake_model)
    assert result.component_scores["evidence"] == 0.72
    assert result.action == "CHALLENGE"
