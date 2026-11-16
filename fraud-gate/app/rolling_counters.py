"""Redis denormalized rolling counters for backward-only device graph features.

Counters read strictly earlier events and are written only after the current
score response, so a request can never observe itself or a future event.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Sequence

from .schemas import HistoryEvent, ScoreRequest
from .temporal_graph import TemporalFeatures, score_temporal

WINDOW_1H = 3_600_000
WINDOW_10M = 600_000


@dataclass(frozen=True)
class RollingCounters:
    """Prior-only velocity/fan-out read from Redis; falls back to supplied history."""

    redis: Any
    prefix: str = "fraud-gate:counters"

    def _device_key(self, device_id: str) -> str:
        return f"{self.prefix}:device:{device_id}"

    def _dest_key(self, device_id: str, destination: str) -> str:
        return f"{self.prefix}:dest:{device_id}:{destination}"

    async def record(self, event: HistoryEvent) -> None:
        now = int(event.timestamp.timestamp() * 1000)
        await self.redis.zadd(self._device_key(event.device_id), {now: now})
        await self.redis.zadd(
            self._dest_key(event.device_id, event.destination), {now: now}
        )
        await self.redis.expire(self._device_key(event.device_id), 7_200)
        await self.redis.expire(self._dest_key(event.device_id, event.destination), 7_200)

    async def _velocity(self, device_id: str, now_ms: int) -> int:
        return int(await self.redis.zcount(
            self._device_key(device_id), max(0, now_ms - WINDOW_10M), now_ms - 1
        ) or 0)

    async def _fanout(self, device_id: str, now_ms: int) -> int:
        # Distinct destinations seen strictly before now; Redis stores one zset
        # per destination, so existence within the window is a distinct set.
        destinations: set[str] = set()
        pattern = f"{self.prefix}:dest:{device_id}:*"
        # Scan is bounded; only prior window membership matters below.
        async for key in self.redis.scan_iter(match=pattern, count=64):
            if int(await self.redis.zcount(key, max(0, now_ms - WINDOW_1H), now_ms - 1) or 0) > 0:
                destinations.add(key.rsplit(":", 1)[-1])
        return len(destinations)

    async def temporal(self, request: ScoreRequest) -> TemporalFeatures:
        """Compute backward-only features from Redis; raise on store failure.

        The caller falls back to ``score_temporal`` on the supplied history so a
        Redis outage fails closed to the deterministic in-request path.
        """
        now_ms = int(request.timestamp.timestamp() * 1000)
        devices = {event.device_id for event in request.history}
        devices.add("current-device")
        velocity = fanout = 0
        for device_id in devices:
            velocity = max(velocity, await self._velocity(device_id, now_ms))
            fanout = max(fanout, await self._fanout(device_id, now_ms))
        velocity_score = max(0.0, min(1.0, (velocity - 2) / 6.0))
        fanout_score = max(0.0, min(1.0, (fanout - 2) / 4.0))
        return TemporalFeatures(
            score=max(velocity_score, fanout_score),
            device_velocity_10m=velocity,
            device_fanout_1h=fanout,
            prior_events_1h=velocity,
        )


async def record_current_events(request: ScoreRequest, counters: RollingCounters) -> None:
    """Persist the current request's events after the response has been decided."""
    for event in request.history:
        try:
            await counters.record(event)
        except Exception:
            # Counter updates are best-effort; they cannot change the decision.
            continue
