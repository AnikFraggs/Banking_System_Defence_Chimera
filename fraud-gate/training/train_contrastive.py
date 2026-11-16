"""Fine-tune bge-small-en-v1.5 with MultipleNegativesRankingLoss.

Input pair JSONL uses scenario_id plus anchor/positive objects (or strings).
Telemetry objects are serialized as sorted, escaped key=value lines so equivalent
mappings always produce identical training text. Optional synthetic hard negatives
and an optional cross-encoder are supported. No evaluation metric is fabricated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .hard_negative_synthesis import load_hard_negatives
    from .offline_common import (
        ValidationError,
        bounded_identifier,
        canonical_json,
        read_jsonl,
        require_mapping,
    )
except ImportError:
    from hard_negative_synthesis import load_hard_negatives  # type: ignore
    from offline_common import (  # type: ignore
        ValidationError,
        bounded_identifier,
        canonical_json,
        read_jsonl,
        require_mapping,
    )

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
MAX_PAIRS = 100_000
MAX_TEXT_CHARS = 16_384
MAX_TELEMETRY_ITEMS = 256


def _canonical_scalar(value: Any, name: str) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"{name} contains a non-finite number")
        return format(value, ".17g")
    if isinstance(value, str):
        if len(value) > MAX_TEXT_CHARS:
            raise ValidationError(f"{name} contains an oversized string")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_TELEMETRY_ITEMS:
            raise ValidationError(f"{name} contains too many list entries")
        return "[" + ",".join(_canonical_scalar_or_object(item, name) for item in value) + "]"
    if isinstance(value, Mapping):
        return canonical_json(dict(value))
    raise ValidationError(f"{name} contains unsupported value type {type(value).__name__}")


def _canonical_scalar_or_object(value: Any, name: str) -> str:
    if isinstance(value, Mapping):
        # canonical_json also rejects NaN and non-string dictionary keys.
        if len(value) > MAX_TELEMETRY_ITEMS:
            raise ValidationError(f"{name} contains too many object entries")
        return canonical_json(value)
    return _canonical_scalar(value, name)


def canonical_key_value(telemetry: Mapping[str, Any]) -> str:
    """Serialize nested telemetry without ambiguous str(dict) ordering/formatting."""
    value = require_mapping(telemetry, "telemetry")
    if len(value) > MAX_TELEMETRY_ITEMS:
        raise ValidationError(f"telemetry exceeds {MAX_TELEMETRY_ITEMS} keys")
    flattened: dict[str, Any] = {}

    def visit(item: Mapping[str, Any], prefix: str) -> None:
        for key in sorted(item):
            if not isinstance(key, str) or not key or len(key) > 128 or "\n" in key or "=" in key:
                raise ValidationError("telemetry keys must be non-empty bounded strings without = or newlines")
            path = f"{prefix}.{key}" if prefix else key
            nested = item[key]
            if isinstance(nested, Mapping):
                if not nested:
                    flattened[path] = {}
                else:
                    visit(nested, path)
            else:
                flattened[path] = nested
            if len(flattened) > MAX_TELEMETRY_ITEMS:
                raise ValidationError("flattened telemetry has too many entries")

    visit(value, "")
    text = "\n".join(f"{key}={_canonical_scalar(flattened[key], key)}" for key in sorted(flattened))
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationError(f"canonical telemetry exceeds {MAX_TEXT_CHARS} characters")
    return text


def _training_text(value: Any, name: str) -> str:
    if isinstance(value, Mapping):
        return canonical_key_value(value)
    if isinstance(value, str) and 1 <= len(value.strip()) <= MAX_TEXT_CHARS:
        return value.strip()
    raise ValidationError(f"{name} must be a telemetry object or bounded non-empty string")


def load_contrastive_pairs(path: str | Path) -> list[dict[str, str]]:
    records = read_jsonl(path, max_records=MAX_PAIRS)
    pairs: list[dict[str, str]] = []
    fingerprints: set[str] = set()
    for index, record in enumerate(records):
        scenario = bounded_identifier(record.get("scenario_id"), f"record[{index}].scenario_id")
        if "anchor" in record or "positive" in record:
            if set(record) != {"scenario_id", "anchor", "positive"}:
                raise ValidationError("pair records require exactly scenario_id, anchor and positive")
            anchor_raw, positive_raw = record.get("anchor"), record.get("positive")
        elif "telemetry" in record and "positive_telemetry" in record:
            if set(record) != {"scenario_id", "telemetry", "positive_telemetry"}:
                raise ValidationError("telemetry pair contains extra keys")
            anchor_raw, positive_raw = record["telemetry"], record["positive_telemetry"]
        else:
            raise ValidationError("each pair requires anchor/positive or telemetry/positive_telemetry")
        anchor = _training_text(anchor_raw, "anchor")
        positive = _training_text(positive_raw, "positive")
        fingerprint = hashlib.sha256((anchor + "\0" + positive).encode("utf-8")).hexdigest()
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        pairs.append({"scenario_id": scenario, "anchor": anchor, "positive": positive})
    if not pairs:
        raise ValidationError("no unique contrastive pairs")
    return pairs


def synthetic_contrastive_pairs(path: str | Path) -> list[dict[str, str]]:
    """Pair synthetic card/timing state with its polymorphic order/event view."""
    pairs = []
    for record in load_hard_negatives(path):
        scenario = bounded_identifier(record["group_id"], "group_id")
        anchor = canonical_key_value({
            "Amount": record["Amount"],
            "Time": record["Time"],
            "card_features": record["card_features"],
        })
        positive = canonical_key_value({
            "events": record["events"],
            "order_memo": record["order_memo"],
        })
        pairs.append({"scenario_id": scenario, "anchor": anchor, "positive": positive})
    return pairs


def combine_pairs(*collections: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    combined: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for collection in collections:
        for pair in collection:
            key = (str(pair["anchor"]), str(pair["positive"]))
            if key not in seen:
                seen.add(key)
                combined.append(dict(pair))
            if len(combined) > MAX_PAIRS:
                raise ValidationError(f"more than {MAX_PAIRS} unique pairs")
    return combined


def _import_heavy(*, cross_encoder: bool = False) -> dict[str, Any]:
    try:
        import torch
        from sentence_transformers import InputExample, SentenceTransformer
        from sentence_transformers.losses import MultipleNegativesRankingLoss
        from torch.utils.data import DataLoader
    except ImportError as exc:
        raise RuntimeError(
            "contrastive training requires optional dependencies torch and "
            "sentence-transformers; install fraud-gate/requirements-training.txt "
            f"(missing: {getattr(exc, 'name', str(exc))})"
        ) from exc
    imports: dict[str, Any] = {
        "torch": torch,
        "InputExample": InputExample,
        "SentenceTransformer": SentenceTransformer,
        "MultipleNegativesRankingLoss": MultipleNegativesRankingLoss,
        "DataLoader": DataLoader,
    }
    if cross_encoder:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "optional cross-encoder training requires sentence-transformers with CrossEncoder; "
                "upgrade using fraud-gate/requirements-training.txt"
            ) from exc
        imports["CrossEncoder"] = CrossEncoder
    return imports


def train(args: argparse.Namespace) -> dict[str, Any]:
    battery_pairs = load_contrastive_pairs(args.battery)
    extra = synthetic_contrastive_pairs(args.synthetic) if args.synthetic else []
    pairs = combine_pairs(battery_pairs, extra)
    if len(pairs) < 2:
        raise ValidationError("at least two unique pairs are required for in-batch negatives")
    imports = _import_heavy(cross_encoder=bool(args.cross_encoder_output))
    torch = imports["torch"]
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    model = imports["SentenceTransformer"](
        args.model, device=args.device, local_files_only=args.local_files_only
    )
    examples = [imports["InputExample"](texts=[pair["anchor"], pair["positive"]]) for pair in pairs]
    loader = imports["DataLoader"](examples, shuffle=True, batch_size=args.batch_size)
    loss = imports["MultipleNegativesRankingLoss"](model=model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.fit(
        train_objectives=[(loader, loss)],
        epochs=args.epochs,
        warmup_steps=args.warmup_steps,
        output_path=str(output),
        show_progress_bar=args.show_progress,
    )

    report: dict[str, Any] = {
        "base_model": args.model,
        "loss": "MultipleNegativesRankingLoss",
        "pairs": len(pairs),
        "battery_pairs": len(battery_pairs),
        "synthetic_pairs": len(extra),
        "epochs": args.epochs,
        "output": str(output),
        "local_files_only": args.local_files_only,
    }
    if args.cross_encoder_output:
        cross = imports["CrossEncoder"](
            args.cross_encoder_model,
            num_labels=1,
            device=args.device,
            local_files_only=args.local_files_only,
        )
        cross_examples = []
        for index, pair in enumerate(pairs):
            cross_examples.append(imports["InputExample"](
                texts=[pair["anchor"], pair["positive"]], label=1.0
            ))
            negative = pairs[(index + 1) % len(pairs)]["positive"]
            cross_examples.append(imports["InputExample"](
                texts=[pair["anchor"], negative], label=0.0
            ))
        cross_loader = imports["DataLoader"](cross_examples, shuffle=True, batch_size=args.batch_size)
        cross.fit(
            train_dataloader=cross_loader,
            epochs=args.epochs,
            warmup_steps=args.warmup_steps,
            output_path=args.cross_encoder_output,
            show_progress_bar=args.show_progress,
        )
        report["cross_encoder"] = {
            "base_model": args.cross_encoder_model,
            "examples": len(cross_examples),
            "output": args.cross_encoder_output,
        }
    report_path = output / "training_run.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--battery", required=True, help="Authorized CHIMERA pair JSONL")
    parser.add_argument("--synthetic", help="Optional validated synthetic hard-negative JSONL")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--local-files-only", action="store_true", help="Never download; use local cache/files")
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--warmup-steps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--show-progress", action="store_true")
    parser.add_argument("--cross-encoder-output", help="Also train an optional cross-encoder here")
    parser.add_argument("--cross-encoder-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    args = parser.parse_args()
    if args.batch_size < 2 or args.epochs < 1 or args.warmup_steps < 0:
        parser.error("batch-size must be >=2, epochs >=1 and warmup-steps >=0")
    print(json.dumps(train(args), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
