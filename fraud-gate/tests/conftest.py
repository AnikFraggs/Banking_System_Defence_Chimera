from __future__ import annotations

from copy import deepcopy

import pytest

from app.card_model import CardModel


class FakeBinaryModel:
    classes_ = [0, 1]

    def __init__(self, probability: float = 0.1) -> None:
        self.probability = probability
        self.last_vector = None

    def predict_proba(self, matrix):
        self.last_vector = matrix.tolist()[0]
        return [[1.0 - self.probability, self.probability]]


@pytest.fixture
def fake_estimator():
    return FakeBinaryModel()


@pytest.fixture
def fake_model(fake_estimator):
    return CardModel(
        model=fake_estimator,
        features=("V1", "V2"),
        version="synthetic-v1",
        threshold=0.5,
    )


@pytest.fixture
def base_payload():
    return {
        "order_id": "order-synthetic-1",
        "paypal_authorization_id": "auth-1",
        "mode": "INITIAL",
        "amount": "42.50",
        "currency": "USD",
        "timestamp": "2026-01-01T12:00:00Z",
        "rail": "CARD",
        "card_features": {"V1": 0.25, "V2": -0.5},
        "telemetry": {
            "keystroke_intervals_ms": [],
            "mouse_movements": [],
        },
        "history": [],
        "evidence": None,
        "context": {
            "step_up_verified": False,
            "prior_evidence_score": None,
            "scenario_id": "pytest",
        },
    }


@pytest.fixture
def make_payload(base_payload):
    def build(**changes):
        payload = deepcopy(base_payload)
        payload.update(changes)
        return payload

    return build
