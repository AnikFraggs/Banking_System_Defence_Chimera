"""Best-effort asynchronous explanation publishing, isolated from decisions."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

EXPLANATION_STREAM = "fraud-gate:explanations"


def deterministic_explanation(job: Mapping[str, Any]) -> str:
    action = str(job.get("action", "CHALLENGE"))
    try:
        score = float(job.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    reasons = job.get("reasons") or []
    codes = [
        str(reason.get("code"))
        for reason in reasons
        if isinstance(reason, Mapping) and reason.get("code")
    ]
    suffix = f" Signals: {', '.join(codes)}." if codes else " No component crossed its review threshold."
    return f"Pre-capture decision {action} at risk score {score:.3f}.{suffix}"


class ExplanationPublisher:
    """Redis Stream publisher; all failures are logged and swallowed."""

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._redis: Any = None

    async def start(self) -> None:
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        except Exception as exc:
            logger.warning("Explanation publisher disabled: %s", exc)
            self._redis = None

    async def publish(self, response: Mapping[str, Any]) -> None:
        if self._redis is None:
            return
        try:
            fields = {
                "decision_id": str(response["decision_id"]),
                "order_id": str(response.get("order_id", "")),
                "score": str(response["score"]),
                "action": str(response["action"]),
                "model_version": str(response["model_version"]),
                "feature_hash": str(response["feature_hash"]),
                "reasons": json.dumps(response.get("reasons", []), separators=(",", ":")),
                "component_scores": json.dumps(
                    response.get("component_scores", {}), separators=(",", ":")
                ),
                "fallback": "1" if response.get("fallback") else "0",
            }
            fields["explanation"] = deterministic_explanation(
                {**response, "reasons": response.get("reasons", [])}
            )
            await self._redis.xadd(EXPLANATION_STREAM, fields, maxlen=10_000, approximate=True)
        except Exception as exc:
            # Explanation delivery is never allowed to change score or settlement.
            logger.warning("Could not publish explanation for %s: %s", response.get("decision_id"), exc)

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
