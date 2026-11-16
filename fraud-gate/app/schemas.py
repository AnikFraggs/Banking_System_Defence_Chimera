"""API contracts and payload bounds for the pre-capture fraud gate."""
from __future__ import annotations

import base64
import binascii
import math
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PayloadModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class Mode(str, Enum):
    INITIAL = "INITIAL"
    RESCORE = "RESCORE"
    QUICK_RECHECK = "QUICK_RECHECK"


class Action(str, Enum):
    CAPTURE = "CAPTURE"
    CHALLENGE = "CHALLENGE"
    VOID = "VOID"


def _parse_aware_iso(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value  # internal component tests/callers may already have parsed it
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be a valid ISO-8601 string") from exc
    else:
        raise ValueError("timestamp must be an ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


class MouseMovement(PayloadModel):
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)
    interval_ms: float = Field(ge=0, le=60_000)


class Telemetry(PayloadModel):
    keystroke_intervals_ms: list[float] = Field(
        default_factory=list, max_length=256
    )
    keystroke_dwell_ms: list[float] = Field(default_factory=list, max_length=256)
    mouse_movements: list[MouseMovement] = Field(
        default_factory=list, max_length=512
    )

    @field_validator("keystroke_intervals_ms", "keystroke_dwell_ms")
    @classmethod
    def bounded_intervals(cls, values: list[float]) -> list[float]:
        if any(not math.isfinite(value) or not 0 <= value <= 60_000 for value in values):
            raise ValueError("keystroke timing values must be finite and between 0 and 60000 ms")
        return values


class HistoryEvent(PayloadModel):
    device_id: str = Field(min_length=1, max_length=128)
    destination: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=38)
    timestamp: datetime

    @field_validator("timestamp", mode="before")
    @classmethod
    def iso_timestamp(cls, value: Any) -> datetime:
        return _parse_aware_iso(value)


class Evidence(PayloadModel):
    metadata: dict[str, str | int | float | bool] = Field(
        default_factory=dict, max_length=32
    )
    ocr_text: str | None = Field(default=None, max_length=8192)
    generator_marker: str | None = Field(default=None, max_length=256)
    pixel_residual: float | None = Field(default=None, ge=0, le=1)
    image_payload: str | None = Field(default=None, max_length=2_666_668)

    @field_validator("image_payload")
    @classmethod
    def bounded_base64_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            payload = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("image_payload must be canonical base64") from exc
        if not 1 <= len(payload) <= 2_000_000:
            raise ValueError("decoded image_payload must contain 1 to 2000000 bytes")
        return value

    @field_validator("metadata")
    @classmethod
    def finite_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key, item in value.items():
            if not key or len(key) > 64:
                raise ValueError("metadata keys must contain 1 to 64 characters")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("metadata numbers must be finite")
        return value


class Context(PayloadModel):
    step_up_verified: bool = False
    prior_evidence_score: float | None = Field(default=None, ge=0, le=1)
    scenario_id: str | None = Field(default=None, max_length=128)


class ScoreRequest(PayloadModel):
    order_id: str = Field(min_length=1, max_length=128)
    paypal_authorization_id: str | None = Field(default=None, max_length=128)
    mode: Mode
    amount: Decimal = Field(gt=0, max_digits=38)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    timestamp: datetime
    rail: Literal["CARD"]
    # Values are checked by CardModel so malformed vectors fail closed with a
    # ScoreResponse/INVALID_FEATURES rather than becoming a generic HTTP 422.
    card_features: dict[str, Any] | None = Field(default=None, max_length=64)
    telemetry: Telemetry = Field(default_factory=Telemetry)
    history: list[HistoryEvent] = Field(default_factory=list, max_length=256)
    evidence: Evidence | None = None
    context: Context = Field(default_factory=Context)

    @field_validator("timestamp", mode="before")
    @classmethod
    def iso_timestamp(cls, value: Any) -> datetime:
        return _parse_aware_iso(value)

    @field_validator("card_features", mode="before")
    @classmethod
    def valid_feature_names(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("card_features must be an object")
        for key in value:
            if not key or len(key) > 64:
                raise ValueError("feature names must contain 1 to 64 characters")
        return value


class Reason(PayloadModel):
    code: str
    message: str
    component: str
    score: float = Field(ge=0, le=1)


class ScoreResponse(PayloadModel):
    decision_id: str
    score: float = Field(ge=0, le=1)
    action: Action
    reasons: list[Reason]
    component_scores: dict[str, float]
    model_version: str
    feature_hash: str
    fallback: bool
    latency_ms: float = Field(ge=0)


class ReadinessResponse(PayloadModel):
    ready: bool
    model_loaded: bool
    model_version: str | None
    error: str | None = None
