"""Canonical, bounded telemetry for asynchronous investigation and memory."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

Scalar = str | int | float | bool | None
_COMPONENT_ALIASES = {
    "card_model": "hgb_score",
    "biometrics": "bot_score",
    "device_velocity": "graph_score",
    "evidence": "evidence_score",
}
_TOP_LEVEL_FEATURES = (
    "fan_out",
    "bot_score",
    "l4_flag",
    "hgb_score",
    "graph_score",
    "evidence_score",
    "device_velocity_10m",
    "device_fanout_1h",
    "step_up_verified",
)
_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _number(value: int | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("telemetry numbers must be finite")
    if number == 0:
        return "0"
    # Twelve significant digits are stable across JSON/Python float boundaries
    # and avoid platform-specific repr details while retaining useful precision.
    rendered = format(number, ".12g")
    if "e" in rendered:
        mantissa, exponent = rendered.split("e")
        rendered = f"{mantissa}e{int(exponent):+d}"
    return rendered


def _flatten(value: Any, prefix: str = "") -> dict[str, Scalar]:
    if not isinstance(value, Mapping):
        raise ValueError("telemetry must be an object")
    flattened: dict[str, Scalar] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        full_key = f"{prefix}.{key}" if prefix else key
        if not _KEY_PATTERN.fullmatch(full_key):
            raise ValueError("telemetry keys must be bounded portable names")
        if isinstance(item, Mapping):
            flattened.update(_flatten(item, full_key))
        elif item is None or isinstance(item, (str, int, float, bool)):
            if isinstance(item, str):
                item = " ".join(item.split())[:256]
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("telemetry numbers must be finite")
            flattened[full_key] = item
        else:
            raise ValueError("telemetry values must be scalar or nested objects")
        if len(flattened) > 64:
            raise ValueError("telemetry is limited to 64 scalar features")
    return flattened


def normalize_telemetry(value: Mapping[str, Any] | None) -> dict[str, Scalar]:
    """Return a new, validated dictionary; never mutate the caller's object."""
    return dict(sorted(_flatten(value or {}).items()))


def canonicalize_telemetry(value: Mapping[str, Any] | None) -> str:
    """Serialize telemetry as sorted ``key=value`` tokens with finite numbers."""
    tokens: list[str] = []
    for key, item in normalize_telemetry(value).items():
        if item is None:
            rendered = "null"
        elif isinstance(item, bool):
            rendered = "true" if item else "false"
        elif isinstance(item, (int, float)):
            rendered = _number(item)
        else:
            rendered = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        tokens.append(f"{key}={rendered}")
    return " ".join(tokens)


def parse_canonical_telemetry(value: str) -> dict[str, Scalar]:
    """Parse this module's canonical representation, not arbitrary expressions."""
    features: dict[str, Scalar] = {}
    for token in value.split():
        key, separator, raw = token.partition("=")
        if not separator or not _KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid canonical telemetry token")
        if raw in {"true", "false", "null"}:
            item: Scalar = raw == "true" if raw != "null" else None
        elif raw.startswith('"'):
            item = json.loads(raw)
        else:
            try:
                item = int(raw) if re.fullmatch(r"-?\d+", raw) else float(raw)
            except ValueError as exc:
                raise ValueError("invalid canonical telemetry number") from exc
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("telemetry numbers must be finite")
        features[key] = item
    return normalize_telemetry(features)


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, Mapping) else {}
    return {}


def telemetry_from_job(job: Mapping[str, Any]) -> dict[str, Scalar]:
    """Build features from explicit telemetry and the existing gate components."""
    source = job.get("structured_telemetry")
    if source is None:
        source = job.get("telemetry")
    if isinstance(source, str) and not source.strip().startswith("{"):
        try:
            features = parse_canonical_telemetry(source)
        except (ValueError, json.JSONDecodeError):
            features = {}
    else:
        features = normalize_telemetry(_mapping(source))

    # Explicit telemetry wins; aliases only supply data absent from that object.
    for key in _TOP_LEVEL_FEATURES:
        if key not in features and key in job:
            features[key] = job[key]  # type: ignore[assignment]
    components = _mapping(job.get("component_scores"))
    for component, alias in _COMPONENT_ALIASES.items():
        if alias not in features and component in components:
            features[alias] = components[component]  # type: ignore[assignment]
    if "fan_out" not in features and "device_fanout_1h" in features:
        features["fan_out"] = features["device_fanout_1h"]
    return normalize_telemetry(features)
