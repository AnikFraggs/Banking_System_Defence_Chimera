"""Generate authorized, synthetic slow-drip card-testing hard negatives offline.

The deterministic backend never sends data anywhere. The OpenAI-compatible backend
is opt-in and sends only schema/range instructions, never source feature rows.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .offline_common import (
        ValidationError,
        bounded_identifier,
        bounded_text,
        canonical_json,
        exact_keys,
        finite_number,
        read_jsonl,
        require_mapping,
        strict_json_loads,
        write_jsonl,
    )
except ImportError:  # Direct execution: python training/hard_negative_synthesis.py
    from offline_common import (  # type: ignore
        ValidationError,
        bounded_identifier,
        bounded_text,
        canonical_json,
        exact_keys,
        finite_number,
        read_jsonl,
        require_mapping,
        strict_json_loads,
        write_jsonl,
    )

FEATURES = [f"V{index}" for index in range(1, 29)]
SCHEMA_VERSION = "chimera.hard_negative.v1"
LABEL = "SYNTHETIC"
ATTACK = "SLOW_DRIP_CARD_TESTING"
MAX_RECORDS = 10_000
MAX_SOURCE_ROWS = 50_000
MAX_EVENTS = 32
MAX_PROMPT_CHARS = 4_000
MAX_RESPONSE_BYTES = 1_000_000
MAX_EVENT_OFFSET_MS = 30 * 24 * 60 * 60 * 1000
MAX_FEATURE_ABS = 30.0
MIN_AMOUNT = 0.01
MAX_AMOUNT = 100.0
SPLITS = {"TRAIN", "HELD_OUT"}
RECORD_KEYS = {
    "schema_version",
    "record_id",
    "label",
    "attack",
    "Class",
    "split",
    "group_id",
    "Time",
    "Amount",
    "log_amount",
    "card_features",
    "order_memo",
    "events",
}
EVENT_KEYS = {"offset_ms", "amount"}
SENSITIVE_COLUMNS = {
    "card",
    "card_number",
    "cardnumber",
    "pan",
    "cvv",
    "cvc",
    "expiry",
    "expiration",
    "account",
    "account_number",
    "account_id",
    "routing_number",
    "iban",
    "customer_id",
    "email",
    "name",
    "address",
}
POSSIBLE_SECRET_TEXT = re.compile(r"(?<!\d)(?:\d[ -]*?){12,19}(?!\d)")
MEMO_TEMPLATES = (
    "Order {order} - {item} replenishment",
    "{merchant} order {order}: {item}",
    "Web purchase {order} / {item}",
    "Receipt {order} — {merchant}",
    "{item} refill ({order})",
    "Online order {order}, {item}",
    "Payment reference {order} - {merchant}",
    "Subscription add-on {order}: {item}",
)
ITEMS = ("desk supplies", "coffee filters", "printer paper", "phone cable", "notebook", "tea")
MERCHANTS = ("North Market", "Cedar Shop", "Blue Basket", "Maple Goods", "Oak Supply")


def _authorized(authorized: bool, simulator: bool) -> None:
    if not authorized and not simulator:
        raise ValidationError(
            "input requires explicit --authorized-input or --simulator-input; "
            "unverified datasets are not accepted"
        )


def load_authorized_csv(
    path: str | Path, *, authorized: bool = False, simulator: bool = False
) -> list[dict[str, float]]:
    """Load only numeric creditcard features from an authorized/simulator CSV."""
    _authorized(authorized, simulator)
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"local authorized CSV is required: {source}")
    rows: list[dict[str, float]] = []
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        required = {"Time", "Class", "Amount", *FEATURES}
        missing = sorted(required - headers)
        if missing:
            raise ValidationError(f"source CSV is missing required columns: {missing}")
        forbidden = sorted(header for header in headers if header.lower() in SENSITIVE_COLUMNS)
        if forbidden:
            raise ValidationError(f"source CSV contains forbidden identity/card columns: {forbidden}")
        for line_number, raw in enumerate(reader, 2):
            if len(rows) >= MAX_SOURCE_ROWS:
                raise ValidationError(f"source CSV exceeds {MAX_SOURCE_ROWS} rows")
            row: dict[str, float] = {}
            for name in ("Time", "Amount", *FEATURES):
                try:
                    value = float(raw[name])
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{source}:{line_number}: {name} must be numeric") from exc
                if not math.isfinite(value):
                    raise ValidationError(f"{source}:{line_number}: {name} must be finite")
                row[name] = value
            if row["Amount"] <= 0:
                raise ValidationError(f"{source}:{line_number}: Amount must be positive")
            if raw["Class"] not in {"0", "1", "0.0", "1.0"}:
                raise ValidationError(f"{source}:{line_number}: Class must be binary")
            rows.append(row)
    if not rows:
        raise ValidationError("source CSV has no data rows")
    return rows


def _check_memo(value: Any) -> str:
    memo = bounded_text(value, "order_memo", maximum=160)
    if POSSIBLE_SECRET_TEXT.search(memo):
        raise ValidationError("order_memo contains a possible card/account number")
    return memo


def validate_hard_negative(record: Any) -> dict[str, Any]:
    """Validate and normalize one complete synthetic record; extra keys are fatal."""
    value = require_mapping(record, "hard negative")
    exact_keys(value, RECORD_KEYS, "hard negative")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValidationError(f"schema_version must be {SCHEMA_VERSION}")
    if value["label"] != LABEL:
        raise ValidationError("every generated row must be labeled SYNTHETIC")
    if value["attack"] != ATTACK:
        raise ValidationError(f"attack must be {ATTACK}")
    if isinstance(value["Class"], bool) or value["Class"] != 1:
        raise ValidationError("synthetic hard negatives must have Class=1")
    if value["split"] not in SPLITS:
        raise ValidationError("split must be TRAIN or HELD_OUT")
    normalized: dict[str, Any] = dict(value)
    normalized["record_id"] = bounded_identifier(value["record_id"], "record_id")
    normalized["group_id"] = bounded_identifier(value["group_id"], "group_id")
    normalized["Time"] = finite_number(
        value["Time"], "Time", minimum=0, maximum=MAX_EVENT_OFFSET_MS / 1000
    )
    normalized["Amount"] = finite_number(
        value["Amount"], "Amount", minimum=MIN_AMOUNT, maximum=MAX_AMOUNT
    )
    normalized["log_amount"] = finite_number(
        value["log_amount"], "log_amount", minimum=-10, maximum=10
    )
    if not math.isclose(normalized["log_amount"], math.log(normalized["Amount"]), abs_tol=1e-8):
        raise ValidationError("log_amount must equal natural-log Amount")
    features = require_mapping(value["card_features"], "card_features")
    exact_keys(features, set(FEATURES), "card_features")
    normalized["card_features"] = {
        name: finite_number(
            features[name], f"card_features.{name}", minimum=-MAX_FEATURE_ABS, maximum=MAX_FEATURE_ABS
        )
        for name in FEATURES
    }
    normalized["order_memo"] = _check_memo(value["order_memo"])
    events = value["events"]
    if not isinstance(events, list) or not 2 <= len(events) <= MAX_EVENTS:
        raise ValidationError(f"events must contain 2 to {MAX_EVENTS} entries")
    normalized_events: list[dict[str, float]] = []
    previous_offset = -1.0
    for index, event in enumerate(events):
        item = require_mapping(event, f"events[{index}]")
        exact_keys(item, EVENT_KEYS, f"events[{index}]")
        offset = finite_number(
            item["offset_ms"], f"events[{index}].offset_ms", minimum=0, maximum=MAX_EVENT_OFFSET_MS
        )
        if offset <= previous_offset:
            raise ValidationError("event offsets must be strictly increasing")
        previous_offset = offset
        normalized_events.append(
            {
                "offset_ms": offset,
                "amount": finite_number(
                    item["amount"], f"events[{index}].amount", minimum=MIN_AMOUNT, maximum=MAX_AMOUNT
                ),
            }
        )
    if not math.isclose(normalized["Time"], previous_offset / 1000, abs_tol=1e-6):
        raise ValidationError("Time must equal the final event offset in seconds")
    if not math.isclose(normalized["Amount"], normalized_events[-1]["amount"], abs_tol=1e-8):
        raise ValidationError("Amount must equal the final synthetic event amount")
    normalized["events"] = normalized_events
    return normalized


def load_hard_negatives(path: str | Path, *, max_records: int = MAX_RECORDS) -> list[dict[str, Any]]:
    records = read_jsonl(path, max_records=max_records)
    validated = [validate_hard_negative(record) for record in records]
    seen: set[str] = set()
    groups: dict[str, str] = {}
    for record in validated:
        fingerprint = record_fingerprint(record)
        if fingerprint in seen:
            raise ValidationError("synthetic input contains duplicate/near-duplicate records")
        seen.add(fingerprint)
        previous = groups.setdefault(record["group_id"], record["split"])
        if previous != record["split"]:
            raise ValidationError("a synthetic group crosses train/held-out partitions")
    return validated


def _memo_family(memo: str) -> str:
    # Dynamic order/merchant words are removed for near-duplicate grouping only.
    normalized = re.sub(r"[^a-z]+", " ", memo.lower()).strip()
    return normalized


def record_fingerprint(record: Mapping[str, Any]) -> str:
    """Canonical deduplication fingerprint; ignores ids and assigned split."""
    content = {
        "features": {name: round(float(record["card_features"][name]), 8) for name in FEATURES},
        "amount": round(float(record["Amount"]), 8),
        "memo": _memo_family(str(record["order_memo"])),
        "events": [
            [round(float(event["offset_ms"]), 3), round(float(event["amount"]), 8)]
            for event in record["events"]
        ],
    }
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def split_by_group(
    records: Sequence[Mapping[str, Any]], *, held_out_fraction: float, seed: int
) -> list[dict[str, Any]]:
    """Split whole near-duplicate groups, deterministically, with no group leakage."""
    if not 0 < held_out_fraction < 1:
        raise ValidationError("held_out_fraction must be strictly between 0 and 1")
    groups = sorted({str(record["group_id"]) for record in records})
    ranked = sorted(groups, key=lambda group: hashlib.sha256(f"{seed}:{group}".encode()).hexdigest())
    held_count = int(round(len(groups) * held_out_fraction))
    if len(groups) >= 2:
        held_count = min(len(groups) - 1, max(1, held_count))
    else:
        held_count = 0
    held_out = set(ranked[:held_count])
    result: list[dict[str, Any]] = []
    for index, original in enumerate(records):
        record = dict(original)
        record["split"] = "HELD_OUT" if record["group_id"] in held_out else "TRAIN"
        record["record_id"] = f"syn-{index:08d}"
        result.append(validate_hard_negative(record))
    train_groups = {record["group_id"] for record in result if record["split"] == "TRAIN"}
    held_groups = {record["group_id"] for record in result if record["split"] == "HELD_OUT"}
    if train_groups & held_groups:
        raise AssertionError("internal error: group leakage")
    return result


def _group_for(features: Mapping[str, float], template: str) -> str:
    quantized = {name: round(float(features[name]), 3) for name in FEATURES}
    digest = hashlib.sha256(canonical_json([quantized, template]).encode()).hexdigest()[:24]
    return f"syn-group-{digest}"


def synthesize_deterministic(
    source_rows: Sequence[Mapping[str, float]],
    *,
    count: int,
    seed: int = 42,
    held_out_fraction: float = 0.2,
) -> list[dict[str, Any]]:
    """Create reproducible timing, memo and PCA-feature perturbations."""
    if isinstance(count, bool) or not 1 <= count <= MAX_RECORDS:
        raise ValidationError(f"count must be in [1, {MAX_RECORDS}]")
    if not source_rows:
        raise ValidationError("at least one authorized source row is required")
    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    # A bounded retry budget prevents an accidental duplicate loop.
    for attempt in range(count * 4):
        if len(candidates) >= count:
            break
        source = source_rows[(attempt + seed) % len(source_rows)]
        template = MEMO_TEMPLATES[attempt % len(MEMO_TEMPLATES)]
        # Deliberately use at least two families for multi-row local/test runs.
        if count > 1 and attempt < 2:
            template = MEMO_TEMPLATES[attempt]
        scale = 0.025 + 0.075 * rng.random()
        features = {
            name: max(-MAX_FEATURE_ABS, min(MAX_FEATURE_ABS, float(source[name]) + rng.gauss(0, scale)))
            for name in FEATURES
        }
        event_count = rng.randint(3, 10)
        offsets = [0.0]
        for _ in range(event_count - 1):
            # Log-normal gaps plus circadian jitter mimic patient, inconsistent automation.
            gap = min(6 * 60 * 60 * 1000, max(5 * 60 * 1000, rng.lognormvariate(10.7, 0.65)))
            gap *= rng.uniform(0.85, 1.15)
            offsets.append(min(MAX_EVENT_OFFSET_MS, offsets[-1] + gap))
        amounts = [round(math.exp(rng.uniform(math.log(0.25), math.log(25.0))), 6) for _ in offsets]
        memo = template.format(
            order=f"{rng.randrange(1000, 1_000_000):06d}",
            item=rng.choice(ITEMS),
            merchant=rng.choice(MERCHANTS),
        )
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_id": f"candidate-{attempt:08d}",
            "label": LABEL,
            "attack": ATTACK,
            "Class": 1,
            "split": "TRAIN",
            "group_id": _group_for(source, template),
            "Time": offsets[-1] / 1000,
            "Amount": amounts[-1],
            "log_amount": math.log(amounts[-1]),
            "card_features": features,
            "order_memo": memo,
            "events": [
                {"offset_ms": offset, "amount": amount}
                for offset, amount in zip(offsets, amounts)
            ],
        }
        validated = validate_hard_negative(record)
        fingerprint = record_fingerprint(validated)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        candidates.append(validated)
    if len(candidates) != count:
        raise ValidationError(f"could generate only {len(candidates)} unique records out of {count}")
    return split_by_group(candidates, held_out_fraction=held_out_fraction, seed=seed)


def _openai_prompt(count: int, seed: int) -> str:
    prompt = f"""Return ONLY strict JSON as {{"records":[...]}} with exactly {count} fully synthetic slow-drip card-testing records. Seed hint: {seed}. Never use real card, account, customer or transaction data. Every object must have exactly these keys: schema_version='{SCHEMA_VERSION}', record_id, label='SYNTHETIC', attack='{ATTACK}', Class=1, split='TRAIN', group_id, Time, Amount, log_amount=ln(Amount), card_features (exactly V1 through V28, finite numbers in [-30,30]), order_memo (ordinary polymorphic retail memo <=160 chars, no long digit sequences), events (2-12 objects with exactly offset_ms and amount). Offsets start at 0, strictly increase, have human-like slow-drip gaps from 5 minutes to 6 hours, and end at Time*1000. Amount equals the last event amount; all amounts are in [0.01,100]. Use unique group_id values for unrelated memo families. No markdown, comments, NaN, extra fields, or settlement instructions."""
    if len(prompt) > MAX_PROMPT_CHARS:
        raise AssertionError("prompt bound was exceeded")
    return prompt


def generate_openai_compatible(
    *,
    base_url: str,
    model: str,
    count: int,
    seed: int,
    held_out_fraction: float,
    api_key_env: str = "OPENAI_API_KEY",
    timeout_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """Call an explicitly configured chat-completions endpoint with bounded I/O."""
    _authorized(True, False)  # caller must separately authorize its source dataset
    if not base_url or not model:
        raise ValidationError("OpenAI-compatible backend requires explicit --base-url and --model")
    if not 1 <= count <= MAX_RECORDS:
        raise ValidationError(f"count must be in [1, {MAX_RECORDS}]")
    if not 1 <= timeout_seconds <= 120:
        raise ValidationError("timeout must be in [1, 120] seconds")
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise ValidationError("LLM endpoint must use HTTPS (HTTP is allowed only for localhost)")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempts = 0
    while len(records) < count and attempts < 4:
        attempts += 1
        requested = min(32, count - len(records))
        body = canonical_json(
            {
                "model": model,
                "temperature": 0.4,
                "seed": seed + attempts - 1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You generate schema-valid synthetic fraud simulator fixtures."},
                    {"role": "user", "content": _openai_prompt(requested, seed + attempts - 1)},
                ],
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = os.environ.get(api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"configured LLM request failed: {exc}") from exc
        if len(payload_bytes) > MAX_RESPONSE_BYTES:
            raise ValidationError("LLM response exceeds the one-megabyte bound")
        try:
            payload = strict_json_loads(payload_bytes.decode("utf-8"), max_bytes=MAX_RESPONSE_BYTES)
            content = payload["choices"][0]["message"]["content"]
            generated = strict_json_loads(content, max_bytes=MAX_RESPONSE_BYTES)
        except (KeyError, IndexError, TypeError, UnicodeError, ValidationError) as exc:
            raise ValidationError("LLM response is not an OpenAI-compatible strict JSON completion") from exc
        batch = generated.get("records") if isinstance(generated, dict) else None
        if not isinstance(batch, list) or len(batch) != requested:
            raise ValidationError(f"LLM must return exactly {requested} records")
        for candidate in batch:
            validated = validate_hard_negative(candidate)
            fingerprint = record_fingerprint(validated)
            if fingerprint not in seen:
                seen.add(fingerprint)
                records.append(validated)
    if len(records) != count:
        raise ValidationError(f"LLM produced {len(records)} unique valid records; requested {count}")
    return split_by_group(records, held_out_fraction=held_out_fraction, seed=seed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Local authorized/simulator creditcard CSV")
    authorization = parser.add_mutually_exclusive_group(required=True)
    authorization.add_argument("--authorized-input", action="store_true")
    authorization.add_argument("--simulator-input", action="store_true")
    parser.add_argument("--output", required=True, help="Synthetic JSONL destination")
    parser.add_argument("--backend", choices=("synthetic", "openai-compatible"), default="synthetic")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--held-out-fraction", type=float, default=0.2)
    parser.add_argument("--base-url", help="Explicit OpenAI-compatible server base URL")
    parser.add_argument("--model", help="Explicit model identifier for the configured server")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()

    rows = load_authorized_csv(
        args.data, authorized=args.authorized_input, simulator=args.simulator_input
    )
    if args.backend == "synthetic":
        records = synthesize_deterministic(
            rows, count=args.count, seed=args.seed, held_out_fraction=args.held_out_fraction
        )
    else:
        if not args.base_url or not args.model:
            parser.error("--base-url and --model are required for openai-compatible backend")
        records = generate_openai_compatible(
            base_url=args.base_url,
            model=args.model,
            count=args.count,
            seed=args.seed,
            held_out_fraction=args.held_out_fraction,
            api_key_env=args.api_key_env,
            timeout_seconds=args.timeout_seconds,
        )
    written = write_jsonl(args.output, records, max_records=MAX_RECORDS)
    print(json.dumps({
        "output": str(Path(args.output)),
        "records": written,
        "train": sum(record["split"] == "TRAIN" for record in records),
        "held_out": sum(record["split"] == "HELD_OUT" for record in records),
        "label": LABEL,
        "backend": args.backend,
    }, indent=2))


if __name__ == "__main__":
    main()
