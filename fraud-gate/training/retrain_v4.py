#!/usr/bin/env python
"""One-shot v4 retrain orchestrator. Every step is optional and skipped when its inputs are absent.

Steps (all outputs land under build-check/v4-retrain unless overridden):
  l4-data      prepare v4 L4 data (rebalance + dev mining + SPML external held-out)
  l4-train     fine-tune the compact WordPiece guard and export int8 ONNX (v4)
  l4-eval      score v1/v4 on the calibration split and test split (semantic-only)
  retrieval    build contrastive pairs (+ optional fine-tune) and measure retrieval vs real Redis
  credit       train credit brain v2 with the ring-grouped adaptive mix
  card         train the card HGB gate (requires the Kaggle creditcard.csv; skipped otherwise)
  wire         train the simulated-wire HGB gate (requires PaySim; skipped otherwise)

Nothing here fabricates a metric: skipped steps are recorded with the reason.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(command: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", default="l4-data,l4-train,l4-eval,retrieval,credit,card,wire")
    parser.add_argument("--work-dir", default="build-check/v4-retrain")
    parser.add_argument("--base-model", default="build-check/l4_base")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--redis-url", default="redis://localhost:6399/0")
    parser.add_argument("--neural-retrieval", action="store_true",
                        help="also evaluate bge-small + ms-marco reranking (downloads models)")
    parser.add_argument("--finetune-retriever", action="store_true",
                        help="also fine-tune the bi-encoder on train-split pairs (needs sentence-transformers)")
    parser.add_argument("--authorized-data", action="store_true",
                        help="assert the input datasets are licensed for this training use")
    args = parser.parse_args()
    if not args.authorized_data:
        parser.error("--authorized-data is required; confirm dataset licences before training")

    work = ROOT / args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    splits = ROOT / "datasets/new_custom_datasets/out"
    v4data = splits / "v4"
    v1 = ROOT / "fraud-gate/training/artifacts/l4_semantic_guard"
    v4 = ROOT / "fraud-gate/training/artifacts/l4_semantic_guard_v4"
    spml = ROOT / "datasets/new_custom_datasets/raw/spml/train.jsonl"
    steps = [step.strip() for step in args.steps.split(",") if step.strip()]
    manifest: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": {}}

    def record(step: str, status: str, detail: str = "", code: int | None = None) -> None:
        manifest["steps"][step] = {"status": status, "detail": detail, "exit_code": code}
        (work / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"[{step}] {status} {detail}", flush=True)

    if "l4-data" in steps:
        if not (splits / "text_train.csv").exists():
            record("l4-data", "skipped", "run `python -m chimera_datasets build` first")
        else:
            command = [PY, "fraud-gate/training/prepare_l4_v4_data.py",
                       "--splits-dir", str(splits), "--output-dir", str(v4data)]
            if spml.exists():
                command += ["--spml", str(spml)]
            if (v1 / "model.int8.onnx").exists():
                command += ["--mine-model", str(v1 / "model.int8.onnx"),
                            "--mine-tokenizer", str(v1 / "encoder")]
            code = run(command, work / "l4-data.log")
            record("l4-data", "ran" if code == 0 else "failed", str(v4data / "MANIFEST_V4.json"), code)

    if "l4-train" in steps:
        if not (v4data / "l4_v4_train.jsonl").exists() or not (ROOT / args.base_model).exists():
            record("l4-train", "skipped", "need l4-data output and a local --base-model")
        else:
            code = run([PY, "fraud-gate/training/train_l4_semantic_guard.py",
                        "--data", str(v4data / "l4_v4_train.jsonl"),
                        "--base-model", args.base_model, "--output", str(v4),
                        "--version", "l4-semantic-v4", "--epochs", str(args.epochs),
                        "--authorized-data"], work / "l4-train.log")
            record("l4-train", "ran" if code == 0 else "failed", str(v4 / "metadata.json"), code)

    if "l4-eval" in steps:
        for name, artifact in (("v1", v1), ("v4", v4)):
            if not (artifact / "model.int8.onnx").exists() or not (v4data / "l4_v4_test.jsonl").exists():
                record(f"l4-eval-{name}", "skipped", "artifact or v4 data missing")
                continue
            code = run([PY, "fraud-gate/training/score_l4_onnx.py",
                        "--data", str(v4data / "l4_v4_test.jsonl"),
                        "--model", str(artifact / "model.int8.onnx"),
                        "--tokenizer", str(artifact / "encoder"),
                        "--out-json", str(work / f"semantic_test_{name}.json"),
                        "--out-probs", str(work / f"semantic_test_{name}.csv")],
                       work / f"l4-eval-{name}.log")
            record(f"l4-eval-{name}", "ran" if code == 0 else "failed",
                   str(work / f"semantic_test_{name}.json"), code)
        print("end-to-end (rules+guard) numbers: run the Java L4RealDataEvaluation; see "
              "fraud-gate/training/README_V4.md", flush=True)

    if "retrieval" in steps:
        pairs = work / "retrieval_pairs.jsonl"
        code = run([PY, "fraud-gate/training/build_retrieval_pairs.py",
                    "--splits-dir", str(splits), "--output", str(pairs)], work / "retrieval-pairs.log")
        record("retrieval-pairs", "ran" if code == 0 else "failed", str(pairs), code)
        retriever = "BAAI/bge-small-en-v1.5"
        if args.finetune_retriever and pairs.exists():
            tuned = work / "bge-small-chimera"
            code = run([PY, "fraud-gate/training/train_contrastive.py", "--battery", str(pairs),
                        "--output", str(tuned), "--epochs", "1"], work / "retrieval-finetune.log")
            record("retrieval-finetune", "ran" if code == 0 else "failed", str(tuned), code)
            if code == 0:
                retriever = str(tuned)
        for matcher in (["hashed", "neural"] if args.neural_retrieval else ["hashed"]):
            command = [PY, "fraud-gate/training/evaluate_case_retrieval.py",
                       "--splits-dir", str(splits), "--matcher", matcher,
                       "--redis-url", args.redis_url,
                       "--output", str(work / f"retrieval_{matcher}.json")]
            if matcher == "neural":
                command += ["--bi-encoder", retriever]
            code = run(command, work / f"retrieval-{matcher}.log")
            record(f"retrieval-{matcher}", "ran" if code == 0 else "failed",
                   "needs a reachable Redis (docker run -d --rm -p 6399:6379 redis:7-alpine)"
                   if code else str(work / f"retrieval_{matcher}.json"), code)

    if "credit" in steps:
        code = run([PY, "ai-brain/training/train_credit_brain.py",
                    "--version", "credit-brain-lr-v2", "--adaptive-train-frac", "0.5",
                    "--out", "ai-brain/models/credit_brain_v2.json",
                    "--report", str(work / "credit_v2_report.json"),
                    "--compare-model", "ai-brain/models/credit_brain_v1.json"], work / "credit.log")
        record("credit", "ran" if code == 0 else "failed", str(work / "credit_v2_report.json"), code)

    for step, csv_path, output, extra in (
        ("card", ROOT / "datasets/new_custom_datasets/raw/creditcard_ulb/creditcard.csv",
         ROOT / "fraud-gate/artifacts/creditcard_hgb.joblib", []),
        ("wire", ROOT / "datasets/new_custom_datasets/raw/paysim/paysim.csv",
         ROOT / "fraud-gate/artifacts/paysim_hgb.joblib", []),
    ):
        if step not in steps:
            continue
        if step == "wire":
            record(step, "skipped", "no wire-schema trainer exists; train_creditcard_hgb.py requires "
                   "Time,V1..V28,Amount,Class (ULB card schema), not PaySim columns")
            continue
        if not csv_path.exists():
            record(step, "skipped", f"{csv_path} missing (fetch with chimera_datasets; Kaggle creds needed)")
            continue
        code = run([PY, "fraud-gate/training/train_creditcard_hgb.py", "--data", str(csv_path),
                    "--output", str(output), "--version", f"{step}-hgb-v4", *extra],
                   work / f"{step}.log")
        record(step, "ran" if code == 0 else "failed", str(output), code)

    manifest["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (work / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
