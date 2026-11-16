from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.biometrics import score_biometrics
from app.evidence import score_evidence
from app.policy import clamp_llm_delta
from app.schemas import Evidence, HistoryEvent, MouseMovement, Telemetry
from app.temporal_graph import score_temporal


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def _history(count: int, *, future: bool = False) -> list[HistoryEvent]:
    delta = timedelta(minutes=1)
    return [
        HistoryEvent(
            device_id="device-a",
            destination=f"destination-{index}",
            amount="10.00",
            timestamp=NOW + delta if future else NOW - delta * (index + 1),
        )
        for index in range(count)
    ]


def test_temporal_features_never_use_future_events():
    baseline = score_temporal(_history(5), NOW)
    with_future = score_temporal(_history(5) + _history(20, future=True), NOW)
    assert with_future == baseline
    assert baseline.device_velocity_10m == 5
    assert baseline.device_fanout_1h == 5
    assert baseline.score == 0.75


def test_temporal_features_ignore_events_outside_window_and_group_by_device():
    old = HistoryEvent(
        device_id="device-a",
        destination="old-destination",
        amount="10",
        timestamp=NOW - timedelta(hours=2),
    )
    other_device = HistoryEvent(
        device_id="device-b",
        destination="other-destination",
        amount="10",
        timestamp=NOW - timedelta(minutes=2),
    )
    features = score_temporal(_history(3) + [old, other_device], NOW)
    assert features.device_velocity_10m == 3
    assert features.device_fanout_1h == 3
    assert features.prior_events_1h == 4


def test_uniform_biometrics_are_high_and_short_or_variable_sessions_are_not():
    automated = score_biometrics(Telemetry(
        keystroke_intervals_ms=[100.0] * 12,
        mouse_movements=[
            MouseMovement(x=float(index), y=0.0, interval_ms=16.0)
            for index in range(12)
        ],
    ))
    variable = score_biometrics(Telemetry(
        keystroke_intervals_ms=[50, 180, 90, 240, 120, 300, 70, 210, 160, 95, 260, 130],
        mouse_movements=[],
    ))
    short = score_biometrics(Telemetry(keystroke_intervals_ms=[100.0] * 3))

    assert automated.score == 1.0
    assert variable.score < 0.5
    assert short.score == 0.0


def test_biometric_mad_is_robust_to_one_outlier():
    result = score_biometrics(Telemetry(
        keystroke_intervals_ms=[100.0] * 11 + [2000.0]
    ))
    assert result.keystroke_uniformity == 1.0


def test_evidence_generator_residual_and_benign_text():
    assert score_evidence(Evidence(generator_marker="Stable Diffusion v2")) == 1.0
    assert score_evidence(Evidence(pixel_residual=0.72)) == 0.72
    benign = Evidence(ocr_text=(
        "INVOICE 1042\nCustomer: Example Buyer\nTotal due: 42.50 USD\n"
        "Thank you for your purchase. Payment is due on receipt.\n"
    ))
    assert score_evidence(benign) < 0.6


def test_llm_delta_clamp_is_bounded_and_rejects_non_finite():
    assert clamp_llm_delta(0.5) == 0.05
    assert clamp_llm_delta(-0.5) == -0.05
    assert clamp_llm_delta(0.02) == 0.02
    assert clamp_llm_delta(0.01, limit=0.02) == 0.01
    with pytest.raises(ValueError):
        clamp_llm_delta(0.1, limit=0.2)
    with pytest.raises(ValueError):
        clamp_llm_delta(math.nan)
