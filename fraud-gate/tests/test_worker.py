from __future__ import annotations

import asyncio

from app.investigator import deterministic_explanation
from app.worker import generate_explanation
from unittest.mock import AsyncMock, Mock

import pytest
from prometheus_client import REGISTRY

import app.worker as worker


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("delta", [-.0501, -.05, .05, .0501])
def test_worker_metrics_follow_published_results(monkeypatch, fallback, delta):
    redis = Mock()
    redis.xgroup_create = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[("stream", [("1-0", {"decision_id": "synthetic", "score": "0.5"})])])
    redis.xadd = AsyncMock()
    redis.xack = AsyncMock()
    debate = Mock(matched_cases=["case"], score_delta=delta)
    run = AsyncMock(side_effect=RuntimeError("synthetic outage")) if fallback else AsyncMock(return_value=debate)
    monkeypatch.setattr(worker, "run_debate", run)
    monkeypatch.setattr(worker, "_result_fields", lambda *args: {"explanation": "synthetic"})
    monkeypatch.setattr(worker, "_consume_verdicts", AsyncMock())
    mode = "fallback" if fallback else "deterministic"
    metric = "chimera_fraud_gate_explanations_total"
    before = REGISTRY.get_sample_value(metric, {"mode": mode})
    delta_before = REGISTRY.get_sample_value("chimera_fraud_gate_llm_delta_count")
    matched_before = REGISTRY.get_sample_value("chimera_fraud_gate_matched_cases_total")
    last_before = REGISTRY.get_sample_value("chimera_fraud_gate_llm_delta_last")
    bounds_before = REGISTRY.get_sample_value("chimera_fraud_gate_llm_delta_out_of_bounds_total")
    asyncio.run(worker.run_worker(redis, once=True))
    redis.xadd.assert_awaited_once()
    redis.xack.assert_awaited_once()
    assert REGISTRY.get_sample_value(metric, {"mode": mode}) == before + 1
    assert REGISTRY.get_sample_value("chimera_fraud_gate_llm_delta_count") == delta_before + (not fallback)
    assert REGISTRY.get_sample_value("chimera_fraud_gate_matched_cases_total") == matched_before + (not fallback)
    assert REGISTRY.get_sample_value("chimera_fraud_gate_llm_delta_last") == (last_before if fallback else delta)
    assert REGISTRY.get_sample_value("chimera_fraud_gate_llm_delta_out_of_bounds_total") == bounds_before + (not fallback and abs(delta) > .05)


JOB = {
    "decision_id": "fg_synthetic",
    "action": "CHALLENGE",
    "score": 0.5,
    "reasons": [{"code": "MODEL_UNAVAILABLE"}],
}


def test_worker_template_and_backend_failure_fallback():
    expected = deterministic_explanation(JOB)
    assert "CHALLENGE" in expected
    assert "MODEL_UNAVAILABLE" in expected

    async def broken_backend(_job):
        raise RuntimeError("synthetic backend outage")

    assert asyncio.run(generate_explanation(JOB, broken_backend)) == expected


def test_worker_optional_backend_cannot_change_decision_fields():
    original = dict(JOB)

    async def backend(_job):
        return "An asynchronous analyst explanation."

    assert asyncio.run(generate_explanation(JOB, backend)) == "An asynchronous analyst explanation."
    assert JOB == original
