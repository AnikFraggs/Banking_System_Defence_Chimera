"""Deterministic component scoring and conservative maximum fusion."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from functools import partial
from typing import Any

from .biometrics import BiometricFeatures, score_biometrics
from .card_model import CardModel, InvalidFeatures, ModelUnavailable
from .evidence import score_evidence
from .policy import decide
from .schemas import Action, Mode, Reason, ScoreRequest
from .temporal_graph import TemporalFeatures, score_temporal


@dataclass(frozen=True)
class GateResult:
    score: float
    action: Action
    reasons: list[Reason]
    component_scores: dict[str, float]
    model_version: str
    fallback: bool


@dataclass(frozen=True)
class _CardResult:
    score: float
    threshold: float
    failure: Reason | None
    model_version: str


def _reason(code: str, message: str, component: str, score: float) -> Reason:
    return Reason(
        code=code,
        message=message,
        component=component,
        score=round(score, 6),
    )


def _score_card(request: ScoreRequest, card_model: CardModel | None) -> _CardResult:
    model_version = card_model.version if card_model is not None else "unavailable"
    if card_model is None:
        return _CardResult(
            0.5,
            0.55,
            _reason(
                "MODEL_UNAVAILABLE",
                "Card model is unavailable; capture requires step-up verification.",
                "card_model",
                0.5,
            ),
            model_version,
        )
    threshold = max(0.55, card_model.threshold)
    try:
        return _CardResult(
            card_model.score(request.card_features), threshold, None, model_version
        )
    except InvalidFeatures as exc:
        failure = _reason(
            "INVALID_FEATURES",
            f"Card features failed validation: {exc}",
            "card_model",
            0.5,
        )
    except ModelUnavailable as exc:
        failure = _reason(
            "MODEL_UNAVAILABLE",
            f"Card scoring failed closed: {exc}",
            "card_model",
            0.5,
        )
    except Exception:
        failure = _reason(
            "MODEL_UNAVAILABLE",
            "Card scoring failed closed due to an unexpected model error.",
            "card_model",
            0.5,
        )
    return _CardResult(0.5, threshold, failure, model_version)


def _score_evidence(request: ScoreRequest) -> float:
    if request.mode is Mode.QUICK_RECHECK:
        return request.context.prior_evidence_score or 0.0
    return score_evidence(request.evidence)


def _combine(
    request: ScoreRequest,
    card: _CardResult,
    temporal: TemporalFeatures,
    biometric: BiometricFeatures,
    evidence_score: float,
) -> GateResult:
    fallback = card.failure is not None
    components = {
        "card_model": round(card.score, 6),
        "device_velocity": round(temporal.score, 6),
        "biometrics": round(biometric.score, 6),
        "evidence": round(evidence_score, 6),
    }
    fused = max(components.values())
    reasons: list[Reason] = []
    if card.failure is not None:
        reasons.append(card.failure)
    elif card.score >= card.threshold or card.score >= 0.80:
        reasons.append(_reason(
            "CARD_MODEL_HIGH",
            "The creditcard gradient-boosting model exceeded its review threshold.",
            "card_model",
            card.score,
        ))
    if temporal.score >= 0.55:
        reasons.append(_reason(
            "DEVICE_BURST",
            (
                "Prior-history device burst: "
                f"{temporal.device_velocity_10m} events/10m, "
                f"{temporal.device_fanout_1h} destinations/1h."
            ),
            "device_velocity",
            temporal.score,
        ))
    if biometric.score >= 0.60:
        reasons.append(_reason(
            "AUTOMATION_PATTERN",
            "Robust session timing and movement signals indicate likely automation.",
            "biometrics",
            biometric.score,
        ))
    if evidence_score >= 0.60:
        reasons.append(_reason(
            "EVIDENCE_ARTIFACT",
            "Supporting evidence contains a suspicious generator or artifact signal.",
            "evidence",
            evidence_score,
        ))

    action = decide(fused, components, fallback=fallback)
    return GateResult(
        score=round(max(0.0, min(1.0, fused)), 6),
        action=action,
        reasons=reasons,
        component_scores=components,
        model_version=card.model_version,
        fallback=fallback,
    )


def score_request(request: ScoreRequest, card_model: CardModel | None) -> GateResult:
    """Synchronous compatibility entry point using the same fusion as both transports."""
    return _combine(
        request,
        _score_card(request, card_model),
        score_temporal(request.history, request.timestamp),
        score_biometrics(request.telemetry),
        _score_evidence(request),
    )


async def score_request_async(
    request: ScoreRequest,
    card_model: CardModel | None,
    *,
    temporal_provider=None,
) -> GateResult:
    """Run the four independent modules concurrently without changing fusion.

    ``temporal_provider`` is an optional async callable returning
    ``TemporalFeatures`` (e.g. Redis rolling counters). When it raises, the
    deterministic in-request ``score_temporal`` path is used instead.
    """
    async def _temporal() -> TemporalFeatures:
        if temporal_provider is not None:
            try:
                return await temporal_provider(request)
            except Exception:
                pass
        return await asyncio.to_thread(score_temporal, request.history, request.timestamp)

    card, temporal, biometric, evidence_score = await asyncio.gather(
        asyncio.to_thread(_score_card, request, card_model),
        _temporal(),
        asyncio.to_thread(score_biometrics, request.telemetry),
        asyncio.to_thread(_score_evidence, request),
    )
    return _combine(request, card, temporal, biometric, evidence_score)


def feature_hash(request: ScoreRequest, model_version: str) -> str:
    canonical = json.dumps(
        {
            "model_version": model_version,
            "request": request.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
