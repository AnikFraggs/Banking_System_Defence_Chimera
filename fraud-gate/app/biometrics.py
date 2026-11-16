"""Bounded robust uniformity signals for scripted browser sessions."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence

from .schemas import MouseMovement, Telemetry


@dataclass(frozen=True)
class BiometricFeatures:
    score: float
    keystroke_uniformity: float
    keystroke_dwell_uniformity: float
    mouse_timing_uniformity: float
    mouse_straightness: float
    mouse_micro_tremor: float


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _robust_uniformity(values: Sequence[float], minimum_samples: int = 8) -> float:
    """Return high risk only for sustained, near-constant timing.

    Median/MAD prevent a single delayed event from hiding automation. Short
    sessions provide no evidence rather than being treated as perfectly uniform.
    """
    if len(values) < minimum_samples:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    robust_cv = mad / max(abs(median), 1.0)
    return _clamp(1.0 - robust_cv / 0.12)


def _straightness(movements: Sequence[MouseMovement]) -> float:
    if len(movements) < 2:
        return 0.0
    displacement = math.hypot(
        movements[-1].x - movements[0].x,
        movements[-1].y - movements[0].y,
    )
    path = sum(
        math.hypot(
            current.x - previous.x,
            current.y - previous.y,
        )
        for previous, current in zip(movements, movements[1:])
    )
    return _clamp(displacement / path) if path > 0 else 0.0


def score_biometrics(telemetry: Telemetry) -> BiometricFeatures:
    key_uniformity = _robust_uniformity(telemetry.keystroke_intervals_ms)
    dwell_uniformity = _robust_uniformity(telemetry.keystroke_dwell_ms)
    intervals = [movement.interval_ms for movement in telemetry.mouse_movements]
    mouse_uniformity = _robust_uniformity(intervals, minimum_samples=12)
    straightness = _straightness(telemetry.mouse_movements)
    micro_tremor = (
        _clamp((1.0 - straightness) / 0.03)
        if len(telemetry.mouse_movements) >= 12 else 0.0
    )

    # A straight path alone is normal. Mechanical timing and absent micro-tremor
    # are supporting signals, so ordinary imprecise mouse movement is not penalized.
    straight_signal = 0.0
    if len(telemetry.mouse_movements) >= 12 and straightness >= 0.97:
        straight_signal = ((straightness - 0.97) / 0.03) * (
            0.4 + 0.3 * mouse_uniformity + 0.3 * (1.0 - micro_tremor)
        )

    score = _clamp(max(
        key_uniformity, dwell_uniformity, mouse_uniformity, straight_signal
    ))
    return BiometricFeatures(
        score=score,
        keystroke_uniformity=key_uniformity,
        keystroke_dwell_uniformity=dwell_uniformity,
        mouse_timing_uniformity=mouse_uniformity,
        mouse_straightness=straightness,
        mouse_micro_tremor=micro_tremor,
    )
