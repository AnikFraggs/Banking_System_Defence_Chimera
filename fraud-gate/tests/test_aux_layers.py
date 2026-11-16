"""Tests for the optional fail-closed auxiliary scoring layers."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.aux_layers import (
    AUX_MODEL_LOADED,
    AUX_SCORES_TOTAL,
    AccountOpeningModel,
    AmlModel,
    AuxLayerService,
    WebAttackModel,
)

ARTIFACTS = Path(__file__).resolve().parents[1] / "training" / "artifacts"
AO_DIR = ARTIFACTS / "account_opening_fraud"
AML_DIR = ARTIFACTS / "aml_laundering"
WA_DIR = ARTIFACTS / "web_attack_guard"


def _have_all() -> bool:
    return all((d / "model.joblib").is_file() and (d / "metadata.json").is_file()
               for d in (AO_DIR, AML_DIR, WA_DIR))


requires_artifacts = pytest.mark.skipif(not _have_all(), reason="auxiliary artifacts not present")


@pytest.fixture(scope="module")
def service() -> AuxLayerService:
    if not _have_all():
        pytest.skip("auxiliary artifacts not present")
    return AuxLayerService(
        account_opening=AccountOpeningModel.load(AO_DIR),
        aml=AmlModel.load(AML_DIR),
        web_attack=WebAttackModel.load(WA_DIR),
    )


def test_empty_service_fails_closed():
    svc = AuxLayerService()
    for result in (svc.score_account_opening({}), svc.score_aml({}), svc.score_web_attack("x")):
        assert result["decision"] == "CHALLENGE"
        assert result["fallback"] is True
        assert result["reason"] == "MODEL_UNAVAILABLE"
    assert svc.status()["account_opening"]["loaded"] is False


def test_metrics_registered():
    # Labelled children exist so scrapers see zero-valued series before traffic.
    assert AUX_MODEL_LOADED.labels(layer="aml") is not None
    assert AUX_SCORES_TOTAL.labels(layer="web_attack", decision="PASS", fallback="false") is not None


@requires_artifacts
def test_web_attack_flags_injection(service):
    result = service.score_web_attack("id=1' OR 1=1; DROP TABLE users;--")
    assert result["decision"] == "CHALLENGE"
    assert result["fallback"] is False
    assert result["score"] >= result["threshold"]


@requires_artifacts
def test_web_attack_passes_benign_text(service):
    result = service.score_web_attack("Those wild office parties at The Economist take place in this city")
    assert result["decision"] == "PASS"
    assert result["fallback"] is False


@requires_artifacts
def test_web_attack_invalid_text_fails_closed(service):
    result = service.score_web_attack("   ")
    assert result["decision"] == "CHALLENGE"
    assert result["fallback"] is True
    assert result["reason"].startswith("INVALID_FEATURES")


@requires_artifacts
def test_account_opening_missing_features_fail_closed(service):
    result = service.score_account_opening({"income": 0.5})
    assert result["decision"] == "CHALLENGE"
    assert result["fallback"] is True
    assert result["reason"].startswith("INVALID_FEATURES")


@requires_artifacts
def test_account_opening_benign_row_passes(service):
    import json
    import pandas as pd
    meta = json.loads((AO_DIR / "metadata.json").read_text())
    cols = meta["features"]["numeric"] + meta["features"]["categorical"]
    df = pd.read_csv(Path(__file__).resolve().parents[2] / "datasets/feedzai_bank_account_fraud/Base.csv", nrows=20)
    benign = df[df["fraud_bool"] == 0].iloc[0][cols].to_dict()
    result = service.score_account_opening(benign)
    assert result["fallback"] is False
    assert result["decision"] in ("PASS", "CHALLENGE")
    assert 0.0 <= result["score"] <= 1.0


@requires_artifacts
def test_aml_missing_fields_fail_closed(service):
    result = service.score_aml({"from_bank": "010"})
    assert result["decision"] == "CHALLENGE"
    assert result["fallback"] is True
    assert result["reason"].startswith("INVALID_FEATURES")


@requires_artifacts
def test_aml_benign_transaction_scores(service):
    import pandas as pd
    t = pd.read_csv(Path(__file__).resolve().parents[2] / "datasets/IBM_AMLworld/HI-Small_Trans.csv", nrows=20)
    t.columns = ["ts", "from_bank", "from_acct", "to_bank", "to_acct", "amt_recv", "recv_ccy",
                 "amt_paid", "pay_ccy", "format", "label"]
    txn = t[t["label"] == 0].iloc[0].drop("label").to_dict()
    result = service.score_aml(txn)
    assert result["fallback"] is False
    assert 0.0 <= result["score"] <= 1.0


@requires_artifacts
def test_api_endpoints_and_metrics():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(card_model=None)) as client:
        ready = client.get("/ready/aux")
        assert ready.status_code == 200
        assert ready.json()["web_attack"]["loaded"] is True

        attack = client.post("/score/web-attack", json={"text": "id=1' OR 1=1; DROP TABLE users;--"})
        assert attack.status_code == 200
        assert attack.json()["decision"] == "CHALLENGE"

        bad = client.post("/score/account-opening", json={"features": {"income": 0.5}})
        assert bad.status_code == 200
        assert bad.json()["decision"] == "CHALLENGE"
        assert bad.json()["fallback"] is True

        metrics = client.get("/metrics").text
        assert "chimera_aux_layer_scores_total" in metrics
        assert "chimera_aux_layer_model_loaded" in metrics
        assert "chimera_aux_layer_latency_ms" in metrics