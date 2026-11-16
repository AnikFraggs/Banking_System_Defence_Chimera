"""Canary labeling-loop wiring in the async debate path (escalate-only invariants)."""
import asyncio
import json
import re

import pytest

from app import debate
from app.canary_guard import CanaryGuard

TOKEN_RE = re.compile(r"cnry-[a-z2-7]{6}-[a-z2-7]{8}")
JOB = {"decision_id": "d-1", "order_id": "o-1", "score": 0.7, "reasons": [], "telemetry": {}}


def _argument(role, summary):
    return json.dumps({
        "role": role, "stance": "INCONCLUSIVE", "confidence": 0.5,
        "evidence_refs": ["decision_score"], "summary": summary,
    })


@pytest.fixture
def guard(monkeypatch, tmp_path):
    g = CanaryGuard(secret=b"0123456789abcdef0123")
    monkeypatch.setattr(debate, "_canary_guard", g)
    monkeypatch.setattr(debate, "_canary_harvest_path", str(tmp_path / "canary_hits.jsonl"))
    return g


def test_leak_discards_llm_argument_forces_zero_delta_and_harvests(guard, tmp_path):
    async def leaking_backend(request):
        token = TOKEN_RE.search(request["instruction"]).group(0)
        return _argument(request["role"], f"sure, the reference id is {token}")

    result = asyncio.run(debate.run_debate(JOB, backend=leaking_backend))
    assert result.canary_escalated is True
    assert result.score_delta == 0.0
    assert "Canary leak confirmed" in result.explanation
    harvested = (tmp_path / "canary_hits.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(harvested) == 2  # both prosecutor and defense leaked
    assert all(json.loads(line)["label"] == 1 for line in harvested)


def test_benign_backend_keeps_normal_delta(guard):
    async def benign_backend(request):
        return _argument(request["role"], "Graph and biometric signals are non-diagnostic.")

    result = asyncio.run(debate.run_debate(JOB, backend=benign_backend))
    assert result.canary_escalated is False
    assert "Canary leak confirmed" not in result.explanation


def test_disabled_guard_is_a_no_op(monkeypatch):
    monkeypatch.setattr(debate, "_canary_guard", None)

    async def backend(request):
        assert "internal reference id" not in request["instruction"]
        return _argument(request["role"], "Benign friction explanation.")

    result = asyncio.run(debate.run_debate(JOB, backend=backend))
    assert result.canary_escalated is False


def test_short_secret_disables_guard(monkeypatch):
    monkeypatch.setenv("CANARY_SECRET", "too-short")
    assert debate._build_canary_guard() is None
    monkeypatch.setenv("CANARY_SECRET", "0123456789abcdef0123")
    assert isinstance(debate._build_canary_guard(), CanaryGuard)