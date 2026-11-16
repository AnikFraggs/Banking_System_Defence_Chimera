"""Backward-looking device velocity and fan-out features from supplied history."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .schemas import HistoryEvent


@dataclass(frozen=True)
class TemporalFeatures:
    score: float
    device_velocity_10m: int
    device_fanout_1h: int
    prior_events_1h: int


def score_temporal(
    history: Sequence[HistoryEvent], now: datetime
) -> TemporalFeatures:
    # Strictly earlier events only: current-time and future records cannot leak
    # into this decision, even if a caller supplies an unsorted history.
    one_hour_ago = now - timedelta(hours=1)
    prior = [
        event
        for event in history
        if one_hour_ago <= event.timestamp < now
    ]
    ten_minutes_ago = now - timedelta(minutes=10)

    velocity_by_device: dict[str, int] = defaultdict(int)
    destinations_by_device: dict[str, set[str]] = defaultdict(set)
    for event in prior:
        destinations_by_device[event.device_id].add(event.destination)
        if event.timestamp >= ten_minutes_ago:
            velocity_by_device[event.device_id] += 1

    velocity = max(velocity_by_device.values(), default=0)
    fanout = max((len(items) for items in destinations_by_device.values()), default=0)

    # Two or fewer recent events/destinations are normal. The linear caps make
    # the score explainable and ensure bounded payloads cannot create inf/NaN.
    velocity_score = max(0.0, min(1.0, (velocity - 2) / 6.0))
    fanout_score = max(0.0, min(1.0, (fanout - 2) / 4.0))
    return TemporalFeatures(
        score=max(velocity_score, fanout_score),
        device_velocity_10m=velocity,
        device_fanout_1h=fanout,
        prior_events_1h=len(prior),
    )
