"""Train a LoRA/PEFT adapter on a user-supplied local 3B-7B causal model.

No model is selected or downloaded implicitly. --model must be a local directory,
--authorized-input is mandatory, and targets are strict verdict JSON with no
settlement action. Heavy dependencies are imported only for actual training.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

try:
    from .offline_common import (
        ValidationError,
        bounded_identifier,
        bounded_text,
        canonical_json,
        read_jsonl,
        require_mapping,
        write_jsonl,
    )
except ImportError:
    from offline_common import (  # type: ignore
        ValidationError,
        bounded_identifier,
        bounded_text,
        canonical_json,
        read_jsonl,
        require_mapping,
        write_jsonl,
    )

VERDICTS = {"FRAUD", "BENIGN", "INCONCLUSIVE"}
MAX_VERDICTS = 100_000
MAX_PROMPT_CHARS = 16_384
MIN_PARAMETERS = 3_000_000_000
MAX_PARAMETERS = 7_000_000_000
SETTLEMENT_KEYS = {
    "action",
    "settlement",
    "settlement_action",
    "recommended_action",
    "capture",
    "void",
    "refund",
    "payout",
}
SETTLEMENT_DIRECTIVE = re.compile(
    r"\b(?:capture|void|refund|settle|payout|release)\s+(?:the\s+)?"
    r"(?:payment|funds|transaction|order|authorization)\b",
    re.IGNORECASE,
)


def _telemetry_prompt(telemetry: Mapping[str, Any]) -> str:
    if len(telemetry) > 256:
        raise ValidationError("telemetry has too many keys")
    # JSON is deterministic and escaped; the model is asked to emit a separate
    # structured verdict, never to perform an action suggested by telemetry.
    serialized = canonical_json(telemetry)
    prompt = (
        "You are an offline fraud analyst. Classify the simulator telemetry as "
        "FRAUD, BENIGN, or INCONCLUSIVE. Return only JSON with verdict, rationale, "
        "and evidence. Do not capture, void, refund, settle, or otherwise act on funds.\n"
        f"Telemetry: {serialized}\nVerdict JSON:"
    )
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValidationError("verdict prompt exceeds the bounded prompt size")
    return prompt


def prepare_verdicts(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate analyst rows and build canonical structured JSON target strings."""
    if not 1 <= len(records) <= MAX_VERDICTS:
        raise ValidationError(f"verdict count must be in [1, {MAX_VERDICTS}]")
    prepared: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for index, record in enumerate(records):
        required = {"scenario_id", "telemetry", "verdict", "rationale", "evidence"}
        if set(record) != required:
            extra = sorted(set(record) - required)
            missing = sorted(required - set(record))
            raise ValidationError(f"verdict[{index}] keys mismatch; missing={missing}, extra={extra}")
        forbidden = SETTLEMENT_KEYS & set(record)
        if forbidden:
            raise ValidationError(f"settlement action fields are forbidden: {sorted(forbidden)}")
        scenario = bounded_identifier(record["scenario_id"], f"verdict[{index}].scenario_id")
        if scenario in identifiers:
            raise ValidationError(f"duplicate scenario_id: {scenario}")
        identifiers.add(scenario)
        verdict = record["verdict"]
        if verdict not in VERDICTS:
            raise ValidationError("verdict must be exactly FRAUD, BENIGN, or INCONCLUSIVE")
        rationale = bounded_text(
            record["rationale"], f"verdict[{index}].rationale", minimum=0, maximum=2000
        )
        if SETTLEMENT_DIRECTIVE.search(rationale):
            raise ValidationError("rationale contains a settlement action directive")
        evidence_raw = record["evidence"]
        if not isinstance(evidence_raw, list) or len(evidence_raw) > 32:
            raise ValidationError("evidence must be a list with at most 32 entries")
        evidence = [
            bounded_text(item, f"verdict[{index}].evidence", maximum=512)
            for item in evidence_raw
        ]
        if any(SETTLEMENT_DIRECTIVE.search(item) for item in evidence):
            raise ValidationError("evidence contains a settlement action directive")
        telemetry = require_mapping(record["telemetry"], f"verdict[{index}].telemetry")
        target = {
            "verdict": verdict,
            "rationale": rationale,
            "evidence": evidence,
        }
        prepared.append({
            "scenario_id": scenario,
            "prompt": _telemetry_prompt(telemetry),
            # A string here is intentional for causal LM tokenization; callers can
            # parse it as strict structured JSON and --prepare-only emits an object.
            "target": canonical_json(target),
        })
    return prepared


def load_verdicts(path: str | Path) -> list[dict[str, str]]:
    return prepare_verdicts(read_jsonl(path, max_records=MAX_VERDICTS))


def _import_heavy() -> dict[str, Any]:
    try:
        import torch
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
    except ImportError as exc:
        raise RuntimeError(
            "LoRA training requires optional torch, transformers and peft dependencies; "
            "install fraud-gate/requirements-training.txt "
            f"(missing: {getattr(exc, 'name', str(exc))})"
        ) from exc
    return {
        "torch": torch,
        "LoraConfig": LoraConfig,
        "TaskType": TaskType,
        "get_peft_model": get_peft_model,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "Trainer": Trainer,
        "TrainingArguments": TrainingArguments,
    }


def train(args: argparse.Namespace) -> dict[str, Any]:
    if not args.authorized_input:
        raise ValidationError("--authorized-input is required for analyst verdict JSONL")
    model_path = Path(args.model)
    if not model_path.is_dir():
        raise ValidationError("--model must be an existing local 3B-7B causal model directory")
    examples = load_verdicts(args.verdicts)
    imports = _import_heavy()
    torch = imports["torch"]
    torch.manual_seed(args.seed)
    tokenizer = imports["AutoTokenizer"].from_pretrained(
        str(model_path), local_files_only=True, use_fast=True
    )
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ValidationError("local tokenizer needs a pad or EOS token")
        tokenizer.pad_token = tokenizer.eos_token
    model = imports["AutoModelForCausalLM"].from_pretrained(
        str(model_path), local_files_only=True
    )
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    if not MIN_PARAMETERS <= parameter_count <= MAX_PARAMETERS:
        raise ValidationError(
            f"local causal model has {parameter_count} parameters; required range is 3B-7B"
        )
    lora_config = imports["LoraConfig"](
        task_type=imports["TaskType"].CAUSAL_LM,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=args.target_modules.split(","),
        bias="none",
    )
    model = imports["get_peft_model"](model, lora_config)

    tokenized = []
    for example in examples:
        prompt_ids = tokenizer(example["prompt"], add_special_tokens=True)["input_ids"]
        target_text = example["target"] + (tokenizer.eos_token or "")
        target_ids = tokenizer(target_text, add_special_tokens=False)["input_ids"]
        if not target_ids or len(target_ids) >= args.max_length:
            raise ValidationError("structured target is empty or exceeds max-length")
        prompt_ids = prompt_ids[-max(1, args.max_length - len(target_ids)):]
        input_ids = prompt_ids + target_ids
        tokenized.append({
            "input_ids": input_ids,
            "labels": [-100] * len(prompt_ids) + target_ids,
            "attention_mask": [1] * len(input_ids),
        })

    class VerdictDataset(torch.utils.data.Dataset):
        def __len__(self) -> int:
            return len(tokenized)

        def __getitem__(self, index: int) -> dict[str, Any]:
            return tokenized[index]

    def collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        width = max(len(item["input_ids"]) for item in batch)
        input_ids, labels, masks = [], [], []
        for item in batch:
            padding = width - len(item["input_ids"])
            input_ids.append(item["input_ids"] + [tokenizer.pad_token_id] * padding)
            labels.append(item["labels"] + [-100] * padding)
            masks.append(item["attention_mask"] + [0] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(masks, dtype=torch.long),
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    training_args = imports["TrainingArguments"](
        output_dir=str(output / "trainer_state"),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        logging_steps=args.logging_steps,
        save_strategy="no",
        report_to=[],
        seed=args.seed,
        remove_unused_columns=False,
    )
    trainer = imports["Trainer"](
        model=model,
        args=training_args,
        train_dataset=VerdictDataset(),
        data_collator=collate,
    )
    result = trainer.train()
    # Only adapter weights/config are saved, not a copy of the 3B-7B base model.
    model.save_pretrained(str(output), safe_serialization=True)
    tokenizer.save_pretrained(str(output))
    report = {
        "base_model": str(model_path),
        "base_parameter_count": parameter_count,
        "examples": len(examples),
        "target_schema": ["verdict", "rationale", "evidence"],
        "settlement_actions_in_targets": False,
        "adapter_output": str(output),
        "trainer_metrics": result.metrics,
    }
    (output / "training_run.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdicts", required=True, help="Authorized analyst verdict JSONL")
    parser.add_argument("--authorized-input", action="store_true", required=True)
    parser.add_argument("--model", required=True, help="Existing local 3B-7B causal model directory")
    parser.add_argument("--output", required=True, help="PEFT adapter destination")
    parser.add_argument("--prepare-only", action="store_true", help="Validate and write structured targets; no ML imports")
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--target-modules", default="q_proj,v_proj")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.prepare_only:
        examples = load_verdicts(args.verdicts)
        output_rows = [
            {
                "scenario_id": example["scenario_id"],
                "prompt": example["prompt"],
                "target": json.loads(example["target"]),
            }
            for example in examples
        ]
        count = write_jsonl(args.output, output_rows, max_records=MAX_VERDICTS)
        print(json.dumps({"prepared": count, "output": args.output}, indent=2))
        return
    if args.max_length < 128 or args.batch_size < 1 or args.gradient_accumulation < 1:
        parser.error("max-length >=128, batch-size >=1 and gradient-accumulation >=1 are required")
    if not 0 <= args.lora_dropout <= 0.5 or args.lora_rank < 1 or args.lora_alpha < 1:
        parser.error("invalid LoRA rank/alpha/dropout")
    print(json.dumps(train(args), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
