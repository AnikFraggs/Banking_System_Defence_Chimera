#!/usr/bin/env python
"""One-shot v5 retrain orchestrator — successor to retrain_v4.py.

Steps (all outputs land under build-check/v5-retrain unless overridden):
  l4-data      prepare v5 L4 data (v4 recipe + JBB + in-the-wild + locked external calib slice)
  l4-train     fine-tune the compact WordPiece guard at --max-length (default 256) and export int8 ONNX
  l4-eval      semantic-only v4 vs v5 on test / external-test / external-full
  l4-java-eval optional end-to-end (rules+guard) Java harness on test + external-test (needs Maven)
  retrieval    contrastive pairs (+ optional fine-tune) and retrieval benchmarks vs real Redis
  credit       retrain credit brain v2 (synthetic; already shipped — optional)
  card         train the card HGB gate on raw/creditcard_ulb/creditcard.csv (skipped if absent)
  wire         simulated-wire gate — skipped: no PaySim-schema trainer exists yet (see V5_DESIGN.md)

Nothing here fabricates a metric: skipped steps are recorded with the reason. This orchestrator
runs training only when invoked; wiring it does not train anything.
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
DEFAULT_MVN = "C:/Users/USER/tools/apache-maven-3.9.9/bin/mvn.cmd"
DEFAULT_JAVA_HOME = "C:/Users/USER/tools/jdk-21.0.13+9"


def run(command: list[str], log: Path, env_extra: dict | None = None) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", default="l4-data,l4-train,l4-eval,retrieval,card,wire")
    parser.add_argument("--work-dir", default="build-check/v5-retrain")
    parser.add_argument("--base-model", default="build-check/l4_base")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--max-length", type=int, default=256,
                        help="v5 default 256 (v4 was 128); trainer enforces 32..256")
    parser.add_argument("--positive-weight", type=float, default=1.0,
                        help="injection-class CE weight; tune on calibration, never on test")
    parser.add_argument("--max-calibration-fpr", type=float, default=0.005)
    parser.add_argument("--redis-url", default="redis://localhost:6399/0")
    parser.add_argument("--neural-retrieval", action="store_true")
    parser.add_argument("--finetune-retriever", action="store_true")
    parser.add_argument("--java-eval", action="store_true",
                        help="also run the end-to-end Java L4RealDataEvaluation (Maven + JDK 21)")
    parser.add_argument("--mvn-cmd", default=os.environ.get("CHIMERA_MVN_CMD", DEFAULT_MVN))
    parser.add_argument("--authorized-data", action="store_true")
    args = parser.parse_args()
    if not args.authorized_data:
        parser.error("--authorized-data is required; confirm dataset licences before training")

    work = ROOT / args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    splits = ROOT / "datasets/new_custom_datasets/out"
    raw = ROOT / "datasets/new_custom_datasets/raw"
    v5data = splits / "v5"
    v4 = ROOT / "fraud-gate/training/artifacts/l4_semantic_guard_v4"
    v5 = ROOT / "fraud-gate/training/artifacts/l4_semantic_guard_v5"
    steps = [step.strip() for step in args.steps.split(",") if step.strip()]
    manifest: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "max_length": args.max_length, "positive_weight": args.positive_weight,
                      "steps": {}}

    def record(step: str, status: str, detail: str = "", code: int | None = None) -> None:
        manifest["steps"][step] = {"status": status, "detail": detail, "exit_code": code}
        (work / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"[{step}] {status} {detail}", flush=True)

    if "l4-data" in steps:
        if not (splits / "text_train.csv").exists():
            record("l4-data", "skipped", "run `python -m chimera_datasets build` first")
        else:
            command = [PY, "fraud-gate/training/prepare_l4_v5_data.py",
                       "--splits-dir", str(splits), "--output-dir", str(v5data)]
            if (raw / "spml/train.jsonl").exists():
                command += ["--spml", str(raw / "spml/train.jsonl")]
            if (raw / "jailbreakbench/harmful-behaviors.csv").exists():
                command += ["--jbb-dir", str(raw / "jailbreakbench")]
            if (raw / "in_the_wild_jailbreaks").exists():
                command += ["--itw-dir", str(raw / "in_the_wild_jailbreaks")]
            if (v4 / "model.int8.onnx").exists():
                command += ["--mine-model", str(v4 / "model.int8.onnx"),
                            "--mine-tokenizer", str(v4 / "encoder")]
            code = run(command, work / "l4-data.log")
            record("l4-data", "ran" if code == 0 else "failed", str(v5data / "MANIFEST_V5.json"), code)

    if "l4-train" in steps:
        if not (v5data / "l4_v5_train.jsonl").exists() or not (ROOT / args.base_model).exists():
            record("l4-train", "skipped", "need l4-data output and a local --base-model")
        else:
            command = [PY, "fraud-gate/training/train_l4_semantic_guard.py",
                       "--data", str(v5data / "l4_v5_train.jsonl"),
                       "--base-model", args.base_model, "--output", str(v5),
                       "--version", "l4-semantic-v5", "--epochs", str(args.epochs),
                       "--max-length", str(args.max_length),
                       "--positive-weight", str(args.positive_weight),
                       "--authorized-data"]
            if (v5data / "l4_v5_calib.jsonl").exists():
                command += ["--calibration-data", str(v5data / "l4_v5_calib.jsonl"),
                            "--max-calibration-fpr", str(args.max_calibration_fpr)]
            code = run(command, work / "l4-train.log")
            record("l4-train", "ran" if code == 0 else "failed", str(v5 / "metadata.json"), code)

    if "l4-eval" in steps:
        eval_sets = {"test": v5data / "l4_v5_test.jsonl",
                     "external_test": v5data / "l4_v5_external_test.jsonl",
                     "external_full": v5data / "l4_v5_external_full.jsonl"}
        for name, artifact in (("v4", v4), ("v5", v5)):
            if not (artifact / "model.int8.onnx").exists():
                record(f"l4-eval-{name}", "skipped", "artifact missing")
                continue
            for set_name, data_path in eval_sets.items():
                if not data_path.exists():
                    record(f"l4-eval-{name}-{set_name}", "skipped", "v5 data missing")
                    continue
                code = run([PY, "fraud-gate/training/score_l4_onnx.py",
                            "--data", str(data_path),
                            "--model", str(artifact / "model.int8.onnx"),
                            "--tokenizer", str(artifact / "encoder"),
                            "--out-json", str(work / f"semantic_{set_name}_{name}.json"),
                            "--out-probs", str(work / f"semantic_{set_name}_{name}.csv")],
                           work / f"l4-eval-{name}-{set_name}.log")
                record(f"l4-eval-{name}-{set_name}", "ran" if code == 0 else "failed",
                       str(work / f"semantic_{set_name}_{name}.json"), code)

    if "l4-java-eval" in steps or args.java_eval:
        mvn = args.mvn_cmd
        java_home = os.environ.get("JAVA_HOME", DEFAULT_JAVA_HOME)
        if not Path(mvn).exists() or not (v5 / "model.int8.onnx").exists():
            record("l4-java-eval", "skipped", "Maven or v5 artifact missing")
        else:
            # Windows-style absolute ROOT: Git Bash $PWD mis-resolves inside the JVM.
            root_win = str(ROOT).replace("\\", "/")
            for set_name, file_name in (("test", "l4_v5_test.jsonl"),
                                        ("external_test", "l4_v5_external_test.jsonl")):
                data_path = v5data / file_name
                if not data_path.exists():
                    record(f"l4-java-eval-{set_name}", "skipped", "v5 data missing")
                    continue
                command = [mvn, "-B", "-pl", "defense-pipeline", "-am", "test",
                           "-Dtest=L4RealDataEvaluation", "-Dsurefire.failIfNoSpecifiedTests=false",
                           f"-Dchimera.eval.input={root_win}/datasets/new_custom_datasets/out/v5/{file_name}",
                           f"-Dchimera.eval.output={root_win}/{args.work_dir}/java_{set_name}_v5.csv",
                           f"-Dchimera.eval.semantic.model={root_win}/fraud-gate/training/artifacts/l4_semantic_guard_v5/model.int8.onnx",
                           f"-Dchimera.eval.semantic.vocab={root_win}/fraud-gate/training/artifacts/l4_semantic_guard_v5/vocab.txt"]
                code = run(command, work / f"java-{set_name}-v5.log", {"JAVA_HOME": java_home})
                record(f"l4-java-eval-{set_name}", "ran" if code == 0 else "failed",
                       str(work / f"java_{set_name}_v5.csv"), code)

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

    if "card" in steps:
        csv_path = raw / "creditcard_ulb/creditcard.csv"
        output = ROOT / "fraud-gate/artifacts/creditcard_hgb.joblib"
        if not csv_path.exists():
            record("card", "skipped", f"{csv_path} missing")
        else:
            code = run([PY, "fraud-gate/training/train_creditcard_hgb.py", "--data", str(csv_path),
                        "--output", str(output), "--version", "card-hgb-v5"], work / "card.log")
            record("card", "ran" if code == 0 else "failed", str(output), code)

    if "wire" in steps:
        record("wire", "skipped", "no PaySim-schema trainer exists yet; see V5_DESIGN.md §5 "
               "(raw/paysim/paysim.csv is downloaded and ready)")

    manifest["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (work / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()