"""Shared asynchronous decision service used by REST and gRPC."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from .card_model import CardModel
from .investigator import ExplanationPublisher
from .rolling_counters import RollingCounters, record_current_events
from .safe_lcb import SafeLcbPolicy, apply_step_up
from .schemas import ScoreRequest, ScoreResponse
from .scoring import feature_hash, score_request_async

# Registered once per process; the REST app and the gRPC server each expose their
# own registry, so scoring is observable on whichever transport is in use.
SCORES_TOTAL = Counter(
    "chimera_fraud_gate_scores_total",
    "Pre-capture scoring decisions, labelled by action and fallback flag.",
    ["action", "fallback"],
)
SCORE_LATENCY_MS = Histogram(
    "chimera_fraud_gate_score_latency_ms",
    "End-to-end pre-capture scoring latency in milliseconds.",
    buckets=(1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500),
)
MODEL_LOADED = Gauge(
    "chimera_fraud_gate_model_loaded",
    "1 when a card scoring model is loaded; 0 when failing closed to CHALLENGE.",
)

FUSION_SCORE = Histogram("chimera_fraud_gate_fusion_score", "Pre-capture fused risk score.", buckets=(0, .1, .25, .35, .5, .75, .85, .95, 1))
COMPONENT_SCORE = Histogram("chimera_fraud_gate_component_score", "Pre-capture component risk score.", ["component"], buckets=(0, .1, .25, .35, .5, .75, .85, .95, 1))
for component in ("card_model", "device_velocity", "biometrics", "evidence"):
    COMPONENT_SCORE.labels(component=component)
for action in ("CAPTURE", "CHALLENGE", "VOID"):
    for fallback in ("true", "false"):
        SCORES_TOTAL.labels(action=action, fallback=fallback)


class DecisionService:
    def __init__(
        self,
        card_model: CardModel | None,
        *,
        explanation_publisher: ExplanationPublisher | None = None,
        step_up_policy: SafeLcbPolicy | None = None,
        rolling_counters: RollingCounters | None = None,
    ) -> None:
        self.card_model = card_model
        self.explanation_publisher = explanation_publisher
        self.step_up_policy = step_up_policy
        self.rolling_counters = rolling_counters
        MODEL_LOADED.set(1 if card_model is not None else 0)

    async def score(self, request: ScoreRequest) -> ScoreResponse:
        started = time.perf_counter()
        provider = self.rolling_counters.temporal if self.rolling_counters else None
        result = await score_request_async(request, self.card_model, temporal_provider=provider)
        action = result.action
        reasons = list(result.reasons)
        if self.step_up_policy is not None:
            action, step_up_reason = apply_step_up(
                result.action, result.score, self.step_up_policy
            )
            if step_up_reason is not None:
                reasons.append(step_up_reason)
        response = ScoreResponse(
            decision_id=f"fg_{uuid.uuid4().hex}",
            score=result.score,
            action=action,
            reasons=reasons,
            component_scores=result.component_scores,
            model_version=result.model_version,
            feature_hash=feature_hash(request, result.model_version),
            fallback=result.fallback,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        SCORES_TOTAL.labels(
            action=response.action.value, fallback=str(response.fallback).lower()
        ).inc()
        SCORE_LATENCY_MS.observe(response.latency_ms)
        FUSION_SCORE.observe(response.score)
        for component in ("card_model", "device_velocity", "biometrics", "evidence"):
            if component in response.component_scores:
                COMPONENT_SCORE.labels(component=component).observe(response.component_scores[component])
        if self.rolling_counters is not None:
            asyncio.create_task(record_current_events(request, self.rolling_counters))
        if self.explanation_publisher is not None:
            payload: dict[str, Any] = {
                **response.model_dump(mode="json"),
                "order_id": request.order_id,
                "context": request.context.model_dump(mode="json"),
            }
            asyncio.create_task(self.explanation_publisher.publish(payload))
        return response