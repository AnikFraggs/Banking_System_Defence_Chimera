# CHIMERA real-data evaluation

> **Update 2026-11-14:** §1–§7 below describe the v1 state and are kept as history. SPML **was**
> since fetched, an external held-out eval and a v4 retrain were run, and the verdict cache was
> added. Current numbers: **§8** and `RESULTS_DOSSIER.md` (repo root). The "external_test is empty"
> and "spml not fetched" statements below are superseded.
>
> **Further update 2026-11-14:** L4 **v5** is fine-tuned and the **card (real ULB) + wire (PaySim)**
> gates are trained and benchmarked vs XGBoost/LightGBM/ProtectAI DeBERTa-v3 — see
> [`MODEL_BENCHMARKS.md`](../../MODEL_BENCHMARKS.md) (repo root). **G1 (SPML-native recall ≥50%
> @ FPR≤2%) is NOT met** by v5 (~16% external recall).

This report records what was actually fetched, built, trained, and measured. It deliberately
separates **measured results** from **tooling that exists but was not run**. No model quality is
claimed for artifacts that were not trained and evaluated here.

## 1. Data fetched (real, public)

| Source | Host | Rows fetched | Licence note | Status |
|---|---|---|---|---|
| `codesagar_v3` (`codesagar/malicious-llm-prompts-v3`) | Hugging Face | 8,760 (7,884 train + 876 test) | Not stated on the page — check before redistributing | Fetched 2026-11-12, sha256 in `raw/MANIFEST.json` |

`spml` and `web_attack` were **not** fetched (no raw folder). The Kaggle tabular sources
(`creditcard_ulb`, `paysim`, `baf`, `ieee_cis`) were **not** fetched: Kaggle credentials are not
present in this environment. They are catalogued but unverified.

## 2. Leakage-safe splits (`chimera_datasets build`, seed 13)

8,692 rows kept after cross-source canonical dedup (68 duplicates removed, 0 label conflicts).
Split by payload hash, so one text cannot appear in two splits.

| Split | Total | Benign (0) | Malicious (1) |
|---|---|---|---|
| train | 6,146 | 4,858 | 1,288 |
| dev | 1,289 | 990 | 299 |
| test | 1,257 | 999 | 258 |
| external_test | 0 | 0 | 0 |

`external_test` is empty because no held-out source (e.g. `spml`) was fetched. **All numbers below
are on the in-domain `test` split, not a held-out source.** Output hashes are locked in
`out/SPLIT_LOCK.json`; the build report is `out/BUILD_REPORT.md`.

### Caveats the build itself raised

- `codesagar_v3` aggregates sub-sources whose label is tied to origin: `HuggingFaceH4/ultrachat_200k`
  is 0% malicious (5,774 rows of benign chat) and `Lakera/gandalf_ignore_instructions` is 100%
  malicious (888 rows). A detector can score well by recognising the origin's style instead of the
  attack. Headline recall on this data is therefore an upper bound on real-world skill, not proof.
- No severity labels exist (0 of 8,692 rows), so severity calibration (Pearson r) is **not** computed.
- `role`, `purpose`, `ip` are empty: rings L1–L3 cannot be scored from this data. Only L4 is evaluated.

## 3. Measured: deterministic L4 baseline on the test split

Detector: `L4_InjectionLeakLayer` offline constructor — `InjectionScanner` (invisible-Unicode / bidi /
homoglyph / nested-encoding / injection-phrasing) + `CanaryTokenRegistry`. **No ONNX semantic guard and
no AI-brain severity refinement** (`SeverityAdvisor.LOCAL_ONLY`).

Run: `L4RealDataEvaluation` (defense-pipeline test) over 1,257 payloads, then `chimera_datasets score`.
Predictions: `out/l4_predictions_deterministic.csv`.

| Metric | Value | Wilson 95% CI |
|---|---|---|
| Recall (malicious detected) | **17.8%** (46 / 258) | 13.6% – 23.0% |
| False-positive rate | **0.30%** (3 / 999) | 0.1% – 0.9% |
| Precision | 93.9% (46 / 49) | 83.5% – 97.9% |

Confusion: TP=46, FP=3, TN=996, FN=212. Decisions issued: 1,208 PASS, 49 CHALLENGE, 0 BLOCK,
0 QUARANTINE. Wall time for 1,257 payloads: 1,450 ms (~1.15 ms/payload, single thread, JDK 21).

These are the numbers **after the phrasing-rule tightening** (§4b). Before it, the same harness
measured TP=39, FP=47, TN=952, FN=219 (recall 15.1%, FPR 4.7%, precision 45.3%): the unanchored
`reveal|print|show` / `exfiltrate|leak|send` alternations matched bare substrings inside benign words
("printing", "revealing") and produced 43 benign-`ultrachat` false positives.

**Interpretation (honest).** The rule-based scanner is tuned for concrete evasion patterns
("ignore previous instructions", zero-width steganography, nested base64, canaries). Most
`codesagar_v3` malicious rows are general jailbreak personas that do not contain those specific
patterns, so deterministic recall is low. This is the expected behaviour of a precision-oriented
rule layer, and it is exactly why the architecture adds a semantic guard for the broader jailbreak
class. The 0.30% FPR (3 rows, all literal zero-width-space artifacts in scraped text) shows the
rules are precise. **Do not read 17.8% as the whole system's recall** — the semantic guard was not
active in this measurement.

## 4. Measured: L4 + trained ONNX semantic guard on the same test split

Detector: `L4_InjectionLeakLayer` with the deterministic scanner + canaries **plus** the trained
`OnnxSemanticInjectionGuard` (dynamic-int8 WordPiece encoder, see §5). Severity is still
`SeverityAdvisor.LOCAL_ONLY` — **no AI-brain refinement** in this measurement. The guard is
escalate-only: it can lift a clean PASS to CHALLENGE or a sub-BLOCK dirty CHALLENGE to BLOCK, and
can never downgrade a concrete detector hit.

Run: `L4RealDataEvaluation` with `-Dchimera.eval.semantic.model` / `.vocab` over the same 1,257
payloads, then `chimera_datasets score`. Predictions: `out/l4_predictions_onnx.csv`.
Guard load status printed by the harness: `configured=true available=true detail=enabled: cached
quantized ONNX semantic guard` (the model actually loaded and ran; this is not a fail-closed result).

| Metric | Deterministic baseline (§3) | **+ ONNX semantic guard** | Wilson 95% CI (ONNX) |
|---|---|---|---|
| Recall | 17.8% (46 / 258) | **88.0%** (227 / 258) | 83.4% – 91.4% |
| False-positive rate | 0.30% (3 / 999) | **1.0%** (10 / 999) | 0.5% – 1.8% |
| Precision | 93.9% (46 / 49) | **95.8%** (227 / 237) | 92.4% – 97.7% |

Confusion (ONNX): TP=227, FP=10, TN=989, FN=31. Decisions: 1,020 PASS, 193 CHALLENGE, 44 BLOCK,
0 QUARANTINE. Wall time for 1,257 payloads: 29,277 ms (~23.3 ms/payload, single thread, JDK 21, CPU).
Per-row inference latency on this (loaded) run: **p50=20 ms, p95=48 ms, max=214 ms**; an idle-host
run measured p50=10 / p95=23 / max=65 ms and an earlier loaded run p50=57 / p95=68 / max=355 ms, so
latency is host/load dependent. All are below the 250 ms timeout.

These are the numbers **after the phrasing-rule tightening** (§4b). Before it the same trained guard
measured TP=229, FP=54, TN=945, FN=29 (recall 88.8%, FPR 5.4%, precision 80.9%). Tightening removed
44 false positives (54 → 10) at the cost of 2 true positives (229 → 227) — see §4b for the trade-off.

### Leakage verification (train vs. this test split)

The guard was trained on `out/l4_train.jsonl` (5,433 rows: 4,335 benign / 1,098 malicious). A direct
comparison against the 1,257-row test split (`out/eval_input.jsonl`) found **0 overlapping payload
hashes** — both raw and NFKC-normalised/lowercased. The training set and this test split are disjoint,
so 88.0% is a genuine held-out number on the in-domain test split, not train-on-test contamination.
(The training script's own internal 4,332/1,101 train/held-out split is a subset of those 5,433 rows
and is separate again from the build's test split.)

### Latency / timeout finding (why the default changed)

Measured CPU inference p50 ranges from **~10 ms (idle host) to ~57 ms (loaded host)**; the upper end
is **above the guard's old 50 ms default timeout**.
Enabling the guard with that old default would have timed out most calls and fail-closed them to
CHALLENGE (`semantic_guard_timeout`), inflating FPR and masking real model skill. The default was
raised to **250 ms** (`OnnxSemanticInjectionGuard` `@Value` + offline constructor, and
`application.yml` `chimera.defense.l4.semantic.timeout-ms`). The eval harness default was also fixed
from an illegal 2000 ms to 1000 ms (the guard rejects timeouts outside [1, 1000] ms). The ~58.9
ms/payload cost is the reason the guard is **opt-in** and the deterministic-first short-circuit
(§4a) matters.

### 4a. Deterministic-first short-circuit (the L4 upgrade)

`inspect()` now runs the cheap deterministic primitives before any ONNX inference:

1. A tripped canary returns **QUARANTINE 0.98** immediately — ONNX is never invoked
   (`semantic_guard_skipped=true`, reason `short_circuited:canary_quarantine`).
2. A deterministic scan hit already at BLOCK severity (`!clean && localSeverity >= 0.7`) skips ONNX
   (`short_circuited:deterministic_block`) and returns BLOCK from the rules alone.
3. Only clean or sub-BLOCK-dirty payloads pay for the semantic model.

This saves the ONNX inference (~10–57 ms/payload) on every canary/high-severity block while preserving
all offline decisions, reasons, and severities. Covered by the 17 defense-pipeline tests (all green)
and the full 69-test gate (17 defense + 52 platform-api, BUILD SUCCESS).

### 4b. Phrasing-rule tightening (the precision fix, measured)

The deterministic scanner's injection-phrasing patterns used unanchored alternations
(`reveal|print|show\s+…prompt` and `exfiltrate|leak|send\s+.*(secret|key|token|credential)`). Because
`|` binds loosely, the bare verbs `reveal`/`print`/`leak` matched **anywhere** — including inside
benign words ("3D **print**ing", "**reveal**ing", "a deeper analysis **reve**als") and "send … key"
across a long paragraph. That produced 43 benign-`ultrachat` false positives.

`InjectionScanner.INJECTION_PATTERNS` now anchors each exfil verb to a sensitive object
(`prompt|instructions|password|secret|confidential|credential|api key|token`) within a few words,
broadens the `ignore … instructions` family, and moves bare `print` to a code-exec token `print(`.
The zero-width / bidi / homoglyph / nested-base64 / canary primitives are **unchanged**.

Measured before → after on the same 1,257-row test split (same trained guard, **no retraining**):

| Metric | Det. before | Det. after | ONNX before | ONNX after |
|---|---|---|---|---|
| TP | 39 | 46 | 229 | 227 |
| FP | 47 | 3 | 54 | 10 |
| Recall | 15.1% | 17.8% | 88.8% | 88.0% |
| FPR | 4.7% | 0.30% | 5.4% | 1.0% |
| Precision | 45.3% | 93.9% | 80.9% | 95.8% |

- **44 false positives removed** (deterministic 47 → 3; combined 54 → 10). Benign-`ultrachat` FP fell
  43 → 2 deterministic (45 → 4 combined). The 3 surviving deterministic FP are all literal
  **zero-width-space** artifacts in scraped text (1 `deepset`, 2 `ultrachat`) — an invisible-Unicode
  hit, not phrasing; that detector is intentionally kept sensitive (the battery's stego family needs it).
- **Cost: 2 combined true positives** (229 → 227). The lost rows are `jackhhao`/`deepset` roleplay
  jailbreaks the old bare-substring rules caught *by accident* (a "print"/"reveal" substring); with the
  rules anchored they fall through to the semantic guard, which misses them. They are now counted
  honestly as false negatives (model skill limits), not masked by a lucky substring match.
- The 7 semantic-added FP are **unchanged** (the guard was not retrained); reducing those is a
  training-data task, not a rule task.
- Deterministic recall actually **rose** (39 → 46 TP): broadening `ignore … instructions` caught 13
  more `gandalf` rows, outweighing 6 `jackhhao` roleplay rows the anchored rules no longer catch.
- **Gate:** the full 69-test suite stays green (17 defense + 52 platform-api, BUILD SUCCESS), including
  `AdversarialValidationTest` (recall ≥ 0.95, precision ≥ 0.90, Pearson r ≥ 0.5 on the 200+ adversarial
  battery) and `EvasionDetectionTest` (homoglyph / nested-base64 / split-canary).

### Interpretation (honest)

- The semantic guard lifts recall from 17.8% to 88.0% on the broad jailbreak class the rules miss,
  at a small FPR increase (0.30% → 1.0%). This is the intended division of labour: precise rules +
  a semantic model for the rest.
- **88.0% is an upper bound, not real-world proof.** The origin-style leakage in §2 still applies:
  the model can partly recognise `ultrachat_200k` (benign) vs `gandalf` (malicious) style. There is
  no held-out external source (`external_test` is empty), so generalisation to unseen attack families
  is **not** measured here.
- No AI-brain severity refinement was active (`LOCAL_ONLY`), and no severity labels exist, so this
  measures binary detection only — not severity calibration.
- The per-payload CPU cost is real (per-row p50 ~10–20 ms; wall ~12.8 ms/payload idle, ~23.3 ms/payload
  on this loaded run). `compose.yaml` now enables the guard by mounting the artifacts (§6); the
  short-circuit keeps rule-blocked requests fast.

### Where the errors are (per-source, measured on the test split)

| sub_source | total | TP | FN | FP | recall within source |
|---|---|---|---|---|---|
| HuggingFaceH4/ultrachat_200k (benign) | 843 | 0 | 0 | 4 | — (FPR 0.47%) |
| jackhhao/jailbreak-classification | 185 | 78 | 11 | 4 | 87.6% |
| Lakera/gandalf_ignore_instructions | 112 | 111 | 1 | 0 | 99.1% |
| deepset/prompt-injections | 103 | 32 | 16 | 1 | 66.7% |
| synthetic | 14 | 6 | 3 | 1 | 66.7% |

- **False positives are now mostly the semantic model, not the rules.** Of 10 FP, only 3 are
  deterministic-only (all literal zero-width-space artifacts: 1 `deepset`, 2 `ultrachat`) and 7 are
  added by the semantic guard (4 `jackhhao`, 2 `ultrachat`, 1 `synthetic`). The phrasing-rule
  tightening (§4b) removed the 43 benign-`ultrachat` rule FPs; the remaining 7 model FPs need
  retraining, not rule changes.
- **False negatives are genuine semantic-model skill limits** (all 31 missed by both layers):
  `deepset` 16 (incl. German-language and low-signal "stop: …" / "Forget everything before that …"
  injections), `jackhhao` 11 (roleplay / character-creation jailbreaks), `synthetic` 3
  (narrative-framed attacks), `gandalf` 1. A PyTorch-vs-ONNX parity check on a sample of these rows
  agreed on the decision 8/8 (max |Δp|=0.15 on one low-confidence row), so the misses are model
  skill, not an export/quantization bug.
- **Origin-style leakage is visible in the per-source recall:** gandalf 99.1% vs deepset 66.7%.
  The headline 88.0% is inflated by the easy, style-distinct gandalf source; real skill on diverse
  injections is closer to the deepset number. This is why an external held-out source is needed.

## 5. Training artifact + tooling status

### Trained and evaluated here (real artifact)

- `fraud-gate/training/train_l4_semantic_guard.py` **was run** on `out/l4_train.jsonl` (codesagar).
  It fine-tunes a compact WordPiece encoder and exports ONNX via `torch.onnx.export` (opset 17) +
  `onnxruntime.quantization.quantize_dynamic` (int8). `optimum` is installed but **not** used for
  export (its exporters are unavailable on the pinned transformers/torch stack).
- Artifacts in `fraud-gate/training/artifacts/l4_semantic_guard/`:
  - `model.int8.onnx` — 11.37 MB, dynamic-int8, the file the Java guard loads.
  - `onnx/model.onnx` — 44.77 MB FP32 (pre-quantization export).
  - `vocab.txt` — 30,522 WordPiece tokens (256 KB).
  - `encoder/` — fine-tuned safetensors + tokenizer; `metadata.json`; `checkpoints/`.
- `metadata.json`: version `l4-semantic-codesagar-v1`, base `build-check/l4_base`,
  parameter_count **11,171,074**, max_length 128, labels {0: BENIGN, 1: INJECTION},
  train_count 4,332 / held_out_count 1,101, eval_loss **0.0612**, eval_runtime 26.17 s,
  artifact_sha256 `6c4e951120b9d5d112d3a84db4e50f958ad0826abff406b4d9020269ef5d479b` (retrained
  2026-11-13; an earlier run produced eval_loss 0.0607 / sha `ffe3dbf9…` and recall 89.5%, within
  run-to-run variance).
- The training script's `eval_loss` is on its **own internal held-out split**, not the build's test
  split. The deployment-relevant detection numbers are the measured §4 recall/FPR on the test split.

### Still NOT run (no artifacts claimed)

- `fraud-gate/training/train_creditcard_hgb.py` / `evaluate_creditcard_hgb.py` — HistGradientBoosting
  card model. Requires the Kaggle `creditcardfraud` CSV (not fetched; `xgboost`/Kaggle creds absent).
  **No card-model artifact was produced.** `fraud-gate/artifacts/` is empty, so the running gate fails
  closed to CHALLENGE.
- `train_contrastive.py`, `train_lora_verdicts.py`, `train_safe_lcb.py`, `hard_negative_synthesis.py` —
  offline tooling, unit-tested (`fraud-gate/tests/test_offline_training_tools.py`, `test_l4_training.py`,
  `test_training.py`) but not executed against real data here.

The fraud-gate and L4 training **tooling** is covered by passing unit tests; that verifies the plumbing.
The L4 semantic guard is the one model actually trained and measured here (§4). No card-fraud or
fine-tuned verdict model is bundled or claimed.

## 6. Reproduce

```bash
# --- build the leakage-safe splits (from datasets/new_custom_datasets, project venv) ---
python -m chimera_datasets build                       # writes out/text_*.csv + BUILD_REPORT.md

# --- CSV -> JSONL for the Java harness (test split) ---
python - <<'PY'
import csv, json
with open('out/text_test.csv', newline='', encoding='utf-8') as f, open('out/eval_input.jsonl','w',encoding='utf-8') as o:
    for r in csv.DictReader(f):
        o.write(json.dumps({'id':r['id'],'payload':r['payload'],'label':int(r['label'])}, ensure_ascii=False)+'\n')
PY

# --- deterministic baseline (no model) ---
# from repo root, JDK 21 + Maven; use a Windows-style absolute ROOT (Git Bash $PWD mis-resolves in Java)
ROOT="C:/Users/USER/OneDrive/Desktop/paypal_hackathon/Banking_System_Defence_Chimera"
mvn -pl defense-pipeline -am test -Dtest=L4RealDataEvaluation -Dsurefire.failIfNoSpecifiedTests=false \
    -Dchimera.eval.input="$ROOT/datasets/new_custom_datasets/out/eval_input.jsonl" \
    -Dchimera.eval.output="$ROOT/datasets/new_custom_datasets/out/l4_predictions_deterministic.csv"
python -m chimera_datasets score out/text_test.csv out/l4_predictions_deterministic.csv

# --- L4 + trained ONNX semantic guard ---
mvn -pl defense-pipeline -am test -Dtest=L4RealDataEvaluation -Dsurefire.failIfNoSpecifiedTests=false \
    -Dchimera.eval.input="$ROOT/datasets/new_custom_datasets/out/eval_input.jsonl" \
    -Dchimera.eval.output="$ROOT/datasets/new_custom_datasets/out/l4_predictions_onnx.csv" \
    -Dchimera.eval.semantic.model="$ROOT/fraud-gate/training/artifacts/l4_semantic_guard/model.int8.onnx" \
    -Dchimera.eval.semantic.vocab="$ROOT/fraud-gate/training/artifacts/l4_semantic_guard/vocab.txt"
python -m chimera_datasets score out/text_test.csv out/l4_predictions_onnx.csv
```

### Enable the guard in the running platform-api (opt-in)

The guard is **disabled by default in `application.yml`** (`model-path`/`vocab-path` empty) so unit
tests and bare runs stay deterministic. **`compose.yaml` now enables it**: it mounts
`./fraud-gate/training/artifacts/l4_semantic_guard` read-only at `/opt/chimera/l4` and sets
`L4_SEMANTIC_MODEL_PATH` / `L4_SEMANTIC_VOCAB_PATH` / `L4_SEMANTIC_TIMEOUT_MS=250` /
`L4_SEMANTIC_THRESHOLD=0.65` (each env-overridable; set the two paths empty to disable). If the
mounted artifacts are absent the guard fails safe to CHALLENGE, never to allow. `render.yaml`
deliberately does **not** set these: the free web plan has no disk for the artifacts, and pointing
at missing files would fail-closed every clean request.

```yaml
# compose.yaml -> services.platform-api (add to environment + volumes)
    environment:
      L4_SEMANTIC_MODEL_PATH: /opt/chimera/l4/model.int8.onnx
      L4_SEMANTIC_VOCAB_PATH: /opt/chimera/l4/vocab.txt
      L4_SEMANTIC_TIMEOUT_MS: "250"      # measured p50~57ms; do not drop below ~100ms on CPU
      L4_SEMANTIC_THRESHOLD: "0.65"
    volumes:
      - ./fraud-gate/training/artifacts/l4_semantic_guard:/opt/chimera/l4:ro
```

On Render the free web plan has no persistent disk, so the artifacts must be baked into the Docker
image (or a disk added on a paid plan) and the same `L4_SEMANTIC_*` env vars set. This deployment path
is **unverified** — only the in-process Java eval (§4) was measured here.

## 7. Test environment

- OS: Windows 11 (10.0.26200), x64. JDK: Temurin 21.0.13. Maven 3.9.9 (host `~/tools`, not on PATH).
- Python: project venv (`build-check/fraud-gate-venv`, Python 3.13). Installed: `torch` 2.15.0,
  `transformers` 5.22.2, `onnx` 1.23.2, `onnxruntime` 1.31.1, `optimum` 2.3.0 (present but unused for
  export), `scikit-learn` 1.6.1, `datasets` 5.2.0, `accelerate` 1.15.0, `safetensors` 0.8.0,
  `numpy` 2.2.5, `pandas` 2.2.3. `xgboost` absent (card model not trained).
- ONNX inference: CPU, single thread (`intraOp=1`, `interOp=1`), int8 quantized model.
- Data fetched unauthenticated from the HF Hub (rate-limited); no Kaggle credentials.
- Java gate: `mvn -pl platform-api -am test` → 69 tests (17 defense + 52 platform-api), 0 failures/errors.

## 8. v4 retrain + external held-out (2026-11-14, measured)

### 8.1 What changed

- **SPML fetched**: `reshabhs/SPML_Chatbot_Prompt_Injection` (HF, MIT), 16,012 rows →
  `raw/spml/train.jsonl`; after canonical dedup against all splits, **15,913 external held-out rows**
  (`out/v4/l4_v4_external.jsonl`): `spml_gandalf` 4,168 (all malicious, degrees 1–5, origin-familiar)
  and `spml_native` 11,745 (3,372 benign + 8,373 malicious, degrees 1–10, genuinely unseen).
- **v4 training data** (`out/v4/MANIFEST_V4.json`): >2000-char rows truncated instead of dropped
  (v1 dropped 713, incl. 188 malicious jackhhao); weak sources oversampled (`repeat`, expanded after
  the grouped split); half of dev mined with v1 (20 errors added at repeat 3), other half reserved
  for calibration; zero exact-normalized train↔test/calib/external overlap.
- **v4 artifact**: `fraud-gate/training/artifacts/l4_semantic_guard_v4/` — same 11,171,074-param
  bert-mini base, int8 ONNX, 6,248 train rows (5,370 unique), internal eval_loss 0.0489 (v1 0.0612;
  different internal splits — compare on the test split below). sha256 `591fdb04b7ae63b2…`.
- **Verdict cache**: `SemanticVerdictCache` (bounded LRU, SHA-256 keys, errors never cached),
  `L4_SEMANTIC_CACHE_SIZE` default 4096.

### 8.2 Test split (same 1,257 rows as §4; end-to-end rules + guard)

| Config | TP/FP/TN/FN | Recall (Wilson 95%) | FPR (Wilson 95%) | Precision |
|---|---|---|---|---|
| v1 @0.65 (§4) | 227/10/989/31 | 88.0% (83.4–91.4) | 1.00% (0.5–1.8) | 95.8% |
| **v4 @0.65** | 235/6/993/23 | **91.1% (87.0–94.0)** | **0.60% (0.3–1.3)** | **97.5%** |
| v1 @calibrated 0.9760 | 203/5/994/55 | 78.7% (73.3–83.2) | 0.50% (0.2–1.2) | 97.6% |
| **v4 @calibrated 0.9642** | 228/3/996/30 | **88.4% (83.9–91.7)** | **0.30% (0.1–0.9)** | 98.7% |

Calibration used the reserved dev half at ≤0.5% FPR (never trained on). Semantic-only per-source:
deepset recall 66.7→77.1%, jackhhao 87.6→89.9% (FP 4→1), synthetic FP 1→0, ultrachat FP 2→2,
gandalf 99.1% both (`build-check/v4-evals/probs_*_test.json`).

Cache replay (same 1,257 rows, second pass): **0 decision mismatches**; p50 45→0.98 ms (v1),
33→0.45 ms (v4); p95 95→10.1 / 80→3.9 ms; 1,256/1,256 eligible hits. First-seen payloads still pay
full inference; the cache only helps repeats.

### 8.3 External SPML (never trained; end-to-end)

| Config | Recall ALL | FPR | gandalf recall | native recall | native FPR |
|---|---|---|---|---|---|
| v1 @0.65 | 28.4% (27.6–29.2) | 4.7% (4.0–5.5) | 74.0% | 5.8% (5.3–6.3) | 4.7% |
| v4 @0.65 | **40.0% (39.2–40.9)** | 9.9% (9.0–11.0) | 86.9% | **16.7% (15.9–17.5)** | 9.9% |
| v4 @calibrated | 34.1% (33.3–34.9) | 6.8% (6.0–7.7) | 81.2% | 10.6% (10.0–11.3) | 6.8% |

**Honest interpretation:** the in-domain 91.1% is an upper bound. On the unseen native distribution
both models are weak; v4 detects ~3× more than v1 but also flags more benign text, and the in-domain
calibrated threshold does not transfer (6.8% external FPR). Recall degrades with obfuscation degree
(native degree 7/10: v4 10.7%/9.4% @0.65). 54.3% of missed native attacks exceed the 128-token window
(long persona preambles bury the injection); the remainder are in-window skill gaps. Nearly all
semantic detections are CHALLENGE (step-up), not BLOCK. Per-degree tables with CIs:
`build-check/v4-evals/spml_degrees_*.txt`; full analysis: `RESULTS_DOSSIER.md` §3.

### 8.4 Reproduce (v4)

```bash
PY=build-check/fraud-gate-venv/Scripts/python.exe
# one-shot orchestrator (skips steps whose inputs are absent; needs Redis for retrieval):
$PY fraud-gate/training/retrain_v4.py --authorized-data --neural-retrieval --redis-url redis://localhost:6399/0
# end-to-end Java evals (absolute paths; surefire cwd = module dir):
bash build-check/v4-evals.sh        # calib -> test@0.65 (+replay) -> test@calibrated -> external x3 -> scores
```

### 8.5 Separate calibration threshold replay (2026-11-14)

`score_l4_onnx.py` now accepts `--calibration-data` and applies a threshold selected on that separate
split to the requested evaluation split. This avoids choosing a threshold on the rows used to report
the result. Using the reserved 650-row v4 calibration split and a nominal 1% FPR budget selected
threshold **0.594414**. The semantic model alone produced:

| Split | TP/FP/TN/FN | Recall | FPR | Precision |
|---|---:|---:|---:|---:|
| v4 test (1,257 rows) | 233/3/996/25 | 90.31% | 0.30% | 98.73% |
| SPML external (15,913 rows) | 4,997/344/3,028/7,544 | 39.85% | 10.20% | 93.56% |
| SPML native only | 1,394/344/3,028/6,979 | 16.65% | 10.20% | 80.21% |

Raw results: `build-check/v4-evals/l4_v4_calibrated_test.json` and
`build-check/v4-evals/l4_v4_calibrated_external.json`. This threshold **is not promoted to production**:
it raises the external FPR and does not improve external native recall over the established v4
operating point. The current production default remains 0.65. The training CLI now supports a bounded
positive-class loss weight and calibration-only threshold selection, but a 256-token candidate
retrain was stopped after 8/782 CPU steps; no candidate artifact or model-quality claim resulted.
