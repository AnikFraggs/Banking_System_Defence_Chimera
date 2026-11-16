"""Small, dependency-free validation helpers shared by offline training tools."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

MAX_JSON_BYTES = 1_000_000
MAX_JSONL_RECORDS = 100_000
MAX_JSONL_LINE_CHARS = 100_000


class ValidationError(ValueError):
    """Input does not satisfy the deliberately narrow offline data contract."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValidationError(f"non-finite JSON number is forbidden: {value}")


def strict_json_loads(text: str, *, max_bytes: int = MAX_JSON_BYTES) -> Any:
    """Parse strict JSON, rejecting duplicate keys, NaN and oversized payloads."""
    if not isinstance(text, str):
        raise ValidationError("JSON input must be text")
    if len(text.encode("utf-8")) > max_bytes:
        raise ValidationError(f"JSON input exceeds {max_bytes} bytes")
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_invalid_constant,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValidationError(f"invalid strict JSON: {exc}") from exc


def read_jsonl(
    path: str | Path,
    *,
    max_records: int = MAX_JSONL_RECORDS,
    max_line_chars: int = MAX_JSONL_LINE_CHARS,
) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"local JSONL input is required: {source}")
    records: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if len(line) > max_line_chars:
                raise ValidationError(f"{source}:{line_number}: line is too long")
            if not line.strip():
                continue
            try:
                value = strict_json_loads(line, max_bytes=max_line_chars * 4)
            except ValidationError as exc:
                raise ValidationError(f"{source}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValidationError(f"{source}:{line_number}: each line must be an object")
            records.append(value)
            if len(records) > max_records:
                raise ValidationError(f"{source}: more than {max_records} records")
    if not records:
        raise ValidationError(f"{source}: no JSONL records")
    return records


def write_jsonl(
    path: str | Path, records: Iterable[Mapping[str, Any]], *, max_records: int = MAX_JSONL_RECORDS
) -> int:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            count += 1
            if count > max_records:
                raise ValidationError(f"refusing to write more than {max_records} records")
            handle.write(
                json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    return count


def require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{name} must be an object")
    return value


def exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    supplied = set(value)
    if supplied != expected:
        missing = sorted(expected - supplied)
        extra = sorted(supplied - expected)
        raise ValidationError(f"{name} keys mismatch; missing={missing}, extra={extra}")


def finite_number(
    value: Any, name: str, *, minimum: float, maximum: float
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValidationError(f"{name} must be finite and in [{minimum}, {maximum}]")
    return number


def bounded_text(value: Any, name: str, *, maximum: int, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    text = value.strip()
    if not minimum <= len(text) <= maximum:
        raise ValidationError(f"{name} length must be in [{minimum}, {maximum}]")
    if any(ord(character) < 32 and character not in "\t\n" for character in text):
        raise ValidationError(f"{name} contains control characters")
    return text


def bounded_identifier(value: Any, name: str) -> str:
    text = bounded_text(value, name, maximum=128)
    if not all(character.isalnum() or character in "_.:-" for character in text):
        raise ValidationError(f"{name} contains unsupported characters")
    return text


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
