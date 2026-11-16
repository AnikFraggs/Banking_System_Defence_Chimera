"""Transparent pre-capture action policy."""
from __future__ import annotations

import math
from typing import Mapping

from .schemas import Action


LOW_RISK_BELOW = 0.35
HIGH_RISK_AT = 0.85
STRONG_CARD_AT = 0.80
STRONG_BURST_AT = 0.75


def decide(
    score: float,
    components: Mapping[str, float],
    *,
    fallback: bool,
) -> Action:
    """Fail closed on model errors, otherwise apply conservative risk bands."""
    if fallback:
        return Action.CHALLENGE

    # Strong card or device-burst signals are explicit hard stops.
    if (
        components["card_model"] >= STRONG_CARD_AT
        or components["device_velocity"] >= STRONG_BURST_AT
        or score >= HIGH_RISK_AT
    ):
        return Action.VOID
    if score >= LOW_RISK_BELOW:
        return Action.CHALLENGE

    # These are normally implied by max fusion, but remain explicit policy
    # guardrails if fusion changes later.
    if components["biometrics"] >= 0.65 or components["evidence"] >= 0.65:
        return Action.CHALLENGE
    return Action.CAPTURE


def clamp_llm_delta(delta: float, limit: float = 0.05) -> float:
    """Bound any offline/asynchronous LLM score adjustment to +/- ``limit``.

    This utility is deliberately not called by pre-capture scoring.
    """
    if not 0 <= limit <= 0.05:
        raise ValueError("LLM adjustment limit must be between 0 and 0.05")
    value = float(delta)
    if not math.isfinite(value):
        raise ValueError("LLM adjustment must be finite")
    bounded = max(-limit, min(limit, value))
    return 0.0 if bounded == -0.0 else bounded
