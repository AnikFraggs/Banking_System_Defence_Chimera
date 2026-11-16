from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from prometheus_client import REGISTRY


def test_score_metrics_count_only_completed_requests(make_payload, fake_model):
    total = "chimera_fraud_gate_scores_total"
    labels = {"action": "CAPTURE", "fallback": "false"}
    before = REGISTRY.get_sample_value(total, labels) or 0
    fused_before = REGISTRY.get_sample_value("chimera_fraud_gate_fusion_score_count") or 0
    component_before = {
        name: REGISTRY.get_sample_value("chimera_fraud_gate_component_score_count", {"component": name}) or 0
        for name in ("card_model", "device_velocity", "biometrics", "evidence")
    }
    with TestClient(create_app(card_model=fake_model)) as client:
        assert client.post("/score/pre-capture", json=make_payload()).status_code == 200
        assert client.post("/score/pre-capture", json=make_payload(amount="0")).status_code == 422
        assert client.get("/metrics").status_code == 200
    assert REGISTRY.get_sample_value(total, labels) == before + 1
    assert REGISTRY.get_sample_value("chimera_fraud_gate_fusion_score_count") == fused_before + 1
    for name, value in component_before.items():
        assert REGISTRY.get_sample_value("chimera_fraud_gate_component_score_count", {"component": name}) == value + 1


RESPONSE_FIELDS = {
    "decision_id",
    "score",
    "action",
    "reasons",
    "component_scores",
    "model_version",
    "feature_hash",
    "fallback",
    "latency_ms",
}


def test_readiness_and_score_api_contract(make_payload, fake_model):
    app = create_app(card_model=fake_model)
    with TestClient(app) as client:
        readiness = client.get("/ready")
        assert readiness.status_code == 200
        assert readiness.json() == {
            "ready": True,
            "model_loaded": True,
            "model_version": "synthetic-v1",
            "error": None,
        }

        response = client.post("/score/pre-capture", json=make_payload())
        assert response.status_code == 200
        body = response.json()
        assert set(body) == RESPONSE_FIELDS
        assert body["decision_id"].startswith("fg_")
        assert body["action"] == "CAPTURE"
        assert body["score"] == 0.1
        assert body["model_version"] == "synthetic-v1"
        assert body["fallback"] is False
        assert len(body["feature_hash"]) == 64
        assert body["latency_ms"] >= 0
        assert set(body["component_scores"]) == {
            "card_model", "device_velocity", "biometrics", "evidence"
        }


def test_api_missing_artifact_is_not_ready_but_scores_fail_closed(make_payload, tmp_path):
    app = create_app(model_path=tmp_path / "not-present.joblib")
    with TestClient(app) as client:
        readiness = client.get("/ready")
        assert readiness.status_code == 503
        assert readiness.json()["model_loaded"] is False
        assert readiness.json()["model_version"] is None

        response = client.post("/score/pre-capture", json=make_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "CHALLENGE"
        assert body["fallback"] is True
        assert body["reasons"][0]["code"] == "MODEL_UNAVAILABLE"


def test_api_rejects_invalid_contract_and_oversized_telemetry(make_payload, fake_model):
    app = create_app(card_model=fake_model)
    with TestClient(app) as client:
        bad_rail = make_payload(rail="BANK")
        assert client.post("/score/pre-capture", json=bad_rail).status_code == 422

        bad_amount = make_payload(amount="0")
        assert client.post("/score/pre-capture", json=bad_amount).status_code == 422

        naive_time = make_payload(timestamp="2026-01-01T12:00:00")
        assert client.post("/score/pre-capture", json=naive_time).status_code == 422

        oversized = make_payload(telemetry={"keystroke_intervals_ms": [100.0] * 257})
        assert client.post("/score/pre-capture", json=oversized).status_code == 422


def test_invalid_feature_values_return_fail_closed_score(make_payload, fake_model):
    app = create_app(card_model=fake_model)
    with TestClient(app) as client:
        response = client.post(
            "/score/pre-capture",
            json=make_payload(card_features={"V1": "not-numeric", "V2": 1.0}),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "CHALLENGE"
    assert body["fallback"] is True
    assert body["reasons"][0]["code"] == "INVALID_FEATURES"


def test_repeated_requests_have_deterministic_features_and_scores(make_payload, fake_model):
    app = create_app(card_model=fake_model)
    with TestClient(app) as client:
        first = client.post("/score/pre-capture", json=make_payload()).json()
        second = client.post("/score/pre-capture", json=make_payload()).json()
    assert first["decision_id"] != second["decision_id"]
    assert first["feature_hash"] == second["feature_hash"]
    assert first["score"] == second["score"]
    assert first["reasons"] == second["reasons"]
