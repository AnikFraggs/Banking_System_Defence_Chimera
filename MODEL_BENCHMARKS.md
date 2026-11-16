# CHIMERA — Model Training & Rival Benchmark Report

**Compiled 2026-11-14. Every number here was measured on this host, not estimated or targeted.**
This report supersedes the stale "card gate untrained / Kaggle not fetched / no wire trainer /
xgboost absent" claims in `BENCHMARK.md` §9, `RESULTS_DOSSIER.md` §1/§6, `PROBLEM_STATEMENT.md`
P6, `V5_DESIGN.md` G5/G6 and `README.md` §3/§7. Raw machine-readable output lives beside each
harness under `fraud-gate/training/benchmarks/` and `ai-brain/training/benchmarks/`.

> **Updated 2026-11-15.** New measured sections:
> - §3.3 L4 two-model ensembles (not adopted).
> - §3.4 L4 v7/v7b with the recorded training set (not adopted).
> - §4.2 credit brain v3 (adopted as the serving default).
> - §5.1 triage hybrid RAG (deployed, escalate-only).
>
> §4.1's live check, §7, §8, §9 and §10 are refreshed; §9.1 lists the genuine datasets still missing.
> Adoption rule for every candidate: adopt only if it beats the current model on the held-out data
> without a worse false-positive rate.

> **Updated 2026-11-16:** §3.5 records the v6-initialized v8 deep-learning/ProtectAI experiment. **Not adopted:** recall improved under the expanded calibration protocol, but new-holdout FPR rose to 3.6%, above 2%; external ranking quality also regressed. The existing baseline and deployed L4 artifacts remain unchanged. §6 and the engineering benchmark record the monitoring and settlement checks; Feedzai/IBM AML files are present locally but were not used in this L4 experiment.

## L4 v9 experiment status — 2026-11-16 (COMPLETE, NOT ADOPTED)

**Trained and benchmarked; see §3.6.** The Qwen dual-view + reliability-gated KD + grouped stacker candidate was trained from v8 on the ROCm GPU and evaluated under a locked 1%-calibration / 2%-test protocol against v6, v8 and ProtectAI. **The hybrid fails promotion:** FPR≤2% and CPU latency pass, but recall regresses vs both v6 and v8; the stacker overfits the meta split and the paired/B view learns nothing usable (ProtectAI-B external FPR .9675). The plain neural v9-A beats v6 on every holdout but still trails v8 on external SPML, and ProtectAI dominates external recall (.968). **No model replaced.** Research-only (No Robots CC-BY-NC-4.0); hybrid not implemented in Java. Eleven helper tests pass; FP32 eager parity verified under CPU torch after a ROCm/CPU exporter tracing discrepancy.

## L4 v10 obfuscation round — 2026-11-16 (COMPLETE, NOT ADOPTED)

**Measured; see §3.7.** Tested Claude's six proposals (`build-check/new_l4_claude/`). The 23-transform obfuscation matrix shows v6 has real blind spots (burial/url-encode/rot13 recall ≈ 0) **and** an "encoded-looking ⇒ malicious" shortcut (hex/spaced/html benign FPR ≈ 1.0). Multi-view max-pool recovers recall but blows FPR to 0.396 on plain benign — **not deployable**. The balanced-augmentation candidate v10, retrained on the **correct v6 base** (33M MiniLM-L12; an earlier 11M-base run was a confound, corrected), **regresses external recall .587 → .336** at FPR .019 even after 14 epochs — **fails the adoption gate**. HackAPrompt pair data is prepared leakage-safe but the pair route needs a >128-token contract change (v9-B already failed). The **canary labeling loop is implemented** (operator-enabled via `CANARY_SECRET`, default OFF; leak ⇒ discard LLM argument, delta→0, escalate, harvest positive; 14 tests pass). **v6 remains deployed and unchanged.** SPML G1 (≥0.50) still unmet (v6 ≈0.42); the open gap is labelled *polite scope-violation* data, not obfuscation. Deployed L4 parameters are now surfaced in the web UI.

## L4 v6 mounted as production guard + Java re-qualification — 2026-11-16

**Decision: MOUNT v6 (user-authorized live-behavior change), not a production-readiness claim.** After v7/v8/v9 all failed promotion, v6 remains the best deployable student. It is now mounted at `fraud-gate/training/artifacts/l4_semantic_guard_v6` (int8 `model.int8.onnx`, SHA `8d7aff30…`, 33,360,770 params, vocab 30,522, max_length 128) and wired in `compose.yaml`. The prior codesagar-v1 guard (11M params) is retained at `artifacts/l4_semantic_guard` for rollback.

**Operating point (calibration-only, never tuned on test).** v6's documented int8 operating point is reused: softmax probability ≥ **3.3335218994773995e-06** (logit margin −12.6115), max calibration FPR 2%. `compose.yaml` sets `L4_SEMANTIC_THRESHOLD` to this value (the generic 0.65 default would mis-calibrate v6). Re-verified on the v6 int8 artifact: internal recall .960 / FPR .020 (150+/500−), external recall .573 / FPR .0173 (2485+/694−).

**Java re-qualification (`L4RealDataEvaluation`, Docker `maven:3.9-eclipse-temurin-21`, full L4 layer = deterministic scanner + canaries + v6 ONNX, timeout 1000 ms for skill measurement):**

| Slice | Rows | TP | FP | TN | FN | Recall | FPR | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| internal calib | 650 | 145 | 12 | 488 | 5 | 0.9667 | 0.0240 | 11 | 12 |
| external calib | 3179 | 1426 | 11 | 683 | 1059 | 0.5738 | 0.0159 | 10 | 11 |

- **Tokenizer + ONNX parity confirmed:** Java WordPiece + int8 ONNX reproduce the Python operating point (external .5738/.0159 vs Python .573/.0173). Model-only FPR is within the 2% budget on both slices.
- **FPR caveat:** the combined layer measures 2.4% FPR on the 500-negative internal slice because the deterministic scanner adds 2 FPs on benign banking text — pre-existing behavior independent of the semantic model. External combined FPR is 1.59%. L4 is escalate-only (CHALLENGE), so FPs trigger step-up, not block.
- **Latency:** p50 ~10–11 ms, p95 ~11–12 ms single-thread CPU; max ~147 ms is first-load warmup, within the 250 ms deployment timeout. Replay pass: 3179 rows, **0 decision mismatches**, full cache hits, p50 ~39 µs.
- **Gating:** `L4SemanticGateTest` 5/5 pass (short metadata skips the model; instruction-length text assessed; deterministic high-severity short-circuit holds).
- **Still unmet:** external recall .574 vs ProtectAI .883; native-SPML G1 gate unmet. Research-only (No Robots). Record: `build-check/l4_v6_mount/java_qualification.json`.

## Auxiliary defence layers: account-opening, AML, web-attack — 2026-11-16

**Decision: BUILD + WIRE three new escalate-only research layers (user-authorized).** These are independent scoring services beside the pre-capture card gate; they do **not** alter the card decision path. Each fails closed to `CHALLENGE` (step-up, never block) when its artifact is absent or features are invalid. All three were trained **inside `chimera-fraud-gate:local` under scikit-learn 1.6.1 / xgboost 3.4.1** so their pickles load in the same runtime as the deployed card artifact (`creditcard-hgb-ulb-sk1.6.1`). Thresholds are calibration-only (FPR budget 1%); each test split is scored once. Trainers require `--authorized-data` and refuse to overwrite an existing artifact.

| Layer | Dataset (synthetic) | Selected model | Test AP | Test recall | Test FPR | Threshold | Beats baseline |
|---|---|---|---|---|---|---|---|
| account_opening | Feedzai BAF `Base.csv` (1.0M rows, 1.10% fraud) | XGBoost | 0.195 | 0.165 | 0.0051 | 0.9256 | yes (LR AP 0.178) |
| aml | IBM AMLworld `HI-Small_Trans.csv` (5.08M rows, 0.10% illicit) | HistGradientBoosting | 0.262 | 0.737 | 0.0181 | 0.00829 | yes (recall@1%FPR 0.606 vs 0.279) |
| web_attack | `web_attack_detection.csv` (570,931 unique sentences) | TF-IDF char_wb(3,5) + LogisticRegression | 0.9998 | 0.9969 | 0.0105 | 0.3506 | yes (regex recall 0.421 / FPR 0.0328) |

- **Account-opening.** Temporal split: train months 0–5 (794,989), calibration month 6 (108,168), test month 7 (96,843). 25 numeric + 5 categorical → 48 encoded features; `-1` sentinels mapped to NaN. XGBoost won on calibration AP; HGB ranked higher on the test holdout (AP 0.212) but was not selected — selection never uses test. Modest recall reflects the synthetic, heavily imbalanced base variant. SHA `9989816b…`.
- **AML.** Temporal 70/15/15 split (test 761,752 rows, 1,561 positives). 53 features incl. train-window-only account/bank aggregates (unknown accounts → 0, no leakage). Because FPR at the chosen thresholds differs across models, adoption uses a **matched-1%-FPR recall comparison**: HGB 0.606 vs logistic 0.279, plus AP dominance. HI-Small is an enriched-illicit variant; production prevalence is lower. SHA `3daaf976…`.
- **Web-attack.** Label 1 = attack (SQLi/XSS/command injection), 0 = benign; 1,224 conflicting-label sentences dropped, exact duplicates collapsed, split by sentence-hash bucket so identical text never spans splits. TF-IDF LR F1 0.992 vs defensive regex F1 0.575. A **sampled, out-of-domain** L4 v6 comparison (1000+/1000−, margin cut −12.6115) gives recall 0.673 / FPR 0.201 — the prompt-injection guard is not a web-attack detector. Near-duplicate attack templates may still span splits; mixed HTTP/general-text corpus. SHA `6bd192da…`.
- **Wiring + observability.** `fraud-gate/app/aux_layers.py` loads the three artifacts (env `ACCOUNT_OPENING_MODEL_DIR` / `AML_MODEL_DIR` / `WEB_ATTACK_MODEL_DIR`, mounted read-only at `/aux-artifacts` in `compose.yaml`) and exposes `POST /score/account-opening`, `POST /score/aml`, `POST /score/web-attack`, `GET /ready/aux`. Prometheus metrics `chimera_aux_layer_{scores_total,latency_ms,model_loaded,score}` (labels `layer`, `decision`, `fallback`); Grafana `fraud-gate.json` panels 13–17 (loaded, decisions/sec, latency, fail-closed rate, risk p95).
- **Verification (in-image, sklearn 1.6.1).** Card + all three artifacts load together; web-attack flags `' OR 1=1 --` (0.965 → CHALLENGE) and passes benign text (0.024 → PASS). `tests/test_aux_layers.py` 10/10 pass; full fraud-gate suite 88 passed / 1 skipped (the 4 `test_l4_v9.py` errors are host-only `transformers` imports absent in the image, pre-existing).
- **Caveats.** All three datasets are **synthetic research data** — not proof of real account-opening, laundering, or web-attack accuracy. Licences (Feedzai CC-BY-NC-ND family, IBM CC-BY-NC family, web-attack MIT) must be verified upstream before redistribution; no local licence files were supplied. Escalate-only; separate integration and real-data qualification required before any production claim.

## Measurement environment (these runs)

Windows 11 10.0.26200 x64, AMD Ryzen 7 9700X (8C/16T), 31.1 GB RAM, AMD Radeon RX 9070 XT 16 GB
(gfx1201). Earlier rows ran torch's default 8 threads; the L4 distillation rows below use 16 threads
and, where stated, ROCm on the RX 9070 XT. Latency (p50/p95) is always single-thread CPU ONNX, as
in production. **System Python 3.14.6** (not the
project venv): scikit-learn 1.9.0, numpy 2.5.2, pandas 3.0.5, xgboost 3.4.1, lightgbm 4.7.0,
torch 2.13.0+cpu, onnxruntime 1.31.1 (CPU), transformers (HF), sentencepiece 0.2.3.
`huggingface_hub` 2.4.0. Internet available; rivals downloaded from the HF Hub.

> This differs from the environment recorded in `RESULTS_DOSSIER.md` (venv 3.13, torch 2.15,
> sklearn 1.6.1). Numbers are **not** mixed across environments; each section states its own.

## Methodology (common discipline)

- **Temporal splits** for tabular fraud (sort by `Time`/`step`, 70/15/15). Random splitting leaks
  future patterns and inflates scores; published "SOTA" ULB numbers are mostly random-split.
- **Thresholds chosen on validation / calibration only**, never on any test slice. Tabular gates
  maximize recall within a fixed FPR budget; L4 uses worst-case FPR across BOTH calibration slices.
- **Held-out test** reported with Wilson 95% CIs where positive counts are small.
- **Rival fairness:** every model sees the identical split, features and input truncation. Rival
  published numbers are cited separately and labelled *not reproduced*.
- **Provenance:** data sha256, row counts, fraud rate, library versions and seed recorded per run.
- **Honesty:** synthetic data measures recovery of the generator's signal, not real-world quality.
  Sandbox/stub-only; no real cards, accounts or production deployment is claimed.

---

## 1. Card fraud gate — ULB `creditcard.csv` (REAL, 284,807 rows)

Data sha256 `76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`. Temporal
70/15/15 → train 199,364 / val 42,721 / test 42,722. Test fraud rate **0.1217% (52 frauds)**.
Features = `V1..V28 + Amount` (29, the strict runtime contract). FPR budget 1% on validation.
Harness: `fraud-gate/training/bench_card_fraud.py` → `benchmarks/card/card_benchmark.{json,md}`.

| Model | ROC-AUC | PR-AUC | Recall@FPR≤1% [Wilson 95%] | Precision | FPR | Brier | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|
| **HGB (production, mine)** | 0.957 | 0.751 | **0.827 [0.70–0.91]** (43/52) | 0.117 | 0.0076 | 0.00054 | 0.76 | 0.87 |
| XGBoost (rival) | **0.979** | **0.767** | 0.769 [0.64–0.86] (40/52) | **0.248** | **0.0028** | 0.00047 | **0.19** | **0.21** |
| LightGBM (rival) | 0.873 | 0.658 | 0.769 [0.64–0.86] (40/52) | 0.111 | 0.0075 | 0.00067 | 0.18 | 0.20 |

**Reading it honestly.**
- My HGB catches the **most fraud at the FPR budget** (recall 0.827 vs 0.769) — the right trade for
  a fail-closed gate that routes to human review. XGBoost is the **stronger ranker** (ROC 0.979,
  PR 0.767), has **2× precision**, **¼ the FPR** and is **4× faster**. LightGBM (this config) is
  weakest on the temporal split.
- **Precision is low (0.11–0.25) because fraud is 0.12%** — at FPR 0.76% over 42,670 benign rows
  there are ~326 false positives vs 43 true. Recall@FPR, not accuracy/precision, is the operating
  metric. The 52-fraud test slice gives **wide recall CIs**; treat point estimates cautiously.
- These are **temporal-split** numbers. Published ULB SOTA (~0.80–0.82 PR-AUC, ~0.97–0.98 ROC-AUC;
  e.g. GA-XGBoost PR-AUC 0.798 / ROC 0.967, stacked ensembles AUC-PR 0.821) are mostly **random
  splits** and are *not directly comparable*. On the harder temporal split my HGB/XGB are in the
  same ballpark.

**Offline artifact deployability verified.** The emitted benchmark artifact `fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib` loads through the strict `CardModel.load` contract: HGB, 29 features, version `creditcard-hgb-ulb-v1`, threshold 0.001601. This is the binary associated with the quality table above.

**Runtime correction, 2026-11-16.** The earlier November 15 observation of a 30-feature synthetic toy failing every simulator score is superseded. The currently mounted `fraud-gate/artifacts/creditcard_hgb.joblib` reports `creditcard-hgb-ulb-sk1.6.1`; `/ready` returns ready/model_loaded true, and actual stub CAPTURE with valid receipts is measured in §6. Missing/invalid features still fail closed. No card model was replaced during the current L4/observability work.

The mounted binary SHA256 is `2895ce9ffe4e54c6c8b9e15a2c0b1058da3c93b546023a4443cf86bd1edac998`; the earlier offline benchmark artifact is `c13d69d0ed9c2d8674c6f0b790731dea64cc3cae66b16529e67e0be39ef52bb8`. They are **not byte-identical**, so the quality table must not be attributed automatically to the exact mounted binary. Runtime readiness/settlement success is not a replacement for its own held-out quality evaluation.

**Recommendation.** HGB preserves the current sklearn runtime contract; XGBoost is an offline ranking/latency alternative. Neither a blend nor a runtime replacement is adopted here.

---

## 2. Wire-transfer gate — PaySim (SYNTHETIC simulator, 6,362,620 rows)

Data sha256 `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b`. Temporal
70/15/15 by `step` → train 4,453,834 / val 954,393 / test 954,393. Test fraud **0.42% (4,008)**;
TRANSFER/CASH_OUT subset 407,406. Features = the 10 named numeric vectors from
`train_paysim_wire.engineer_features` (shared train==inference). FPR budget 1% on validation.
Harness: `fraud-gate/training/bench_wire_fraud.py` → `benchmarks/wire/wire_benchmark.{json,md}`.

| Model | ROC-AUC | PR-AUC | Recall@FPR≤1% | Precision | FPR | subset PR | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|
| **HGB (production, mine)** | 1.000 | 1.000 | 0.9968 (3995/4008) | 1.000 | 0.0000 | 1.000 | 1.91 | 3.20 |
| XGBoost (rival) | 1.000 | 0.99995 | 0.9970 (3996/4008) | 1.000 | 0.0000 | 0.99995 | 0.65 | 2.02 |
| LightGBM (rival) | 1.000 | 0.99999 | 0.9965 (3994/4008) | 1.000 | 0.0000 | 0.99999 | **0.43** | **1.29** |

**Read this with care — the ~1.0 scores are a property of the SYNTHETIC data, not model skill.**
PaySim generates fraud deterministically (a TRANSFER/CASH_OUT that drains the origin balance), so the
classes are trivially separable; every strong tree model saturates at AUC≈1.0, FPR≈0. **These numbers
must NOT be cited as real-world wire-fraud detection quality.** The genuine, honest outcomes are:
- **G6 closed:** a PaySim-schema trainer now exists (`train_paysim_wire.py`) and the emitted artefact
  `benchmarks/wire/paysim_wire_hgb.joblib` satisfies the strict `CardModel.load` contract
  (`model_type=paysim-wire`, 10 features, threshold ∈ [0,1]). Previously there was **no trainer**.
- **Latency is the real differentiator** on this trivially-separable data: LightGBM 0.43 ms <
  XGBoost 0.65 ms < HGB 1.91 ms (p50, single row). All are far below the 250 ms gate budget.
- Recall ≈ 0.997 at FPR 0 means ~13 edge-case frauds missed; on real wire data the separation would
  be far harder and these metrics would not hold.

---

## 3. L4 semantic injection guard — locked v5 held-out slices

Harness: `fraud-gate/training/bench_l4_guard.py` → `benchmarks/l4/l4_benchmark.{json,md}`.
**Protocol:** every scorer sees `max_length=128`; ONE threshold per model = worst-case FPR ≤ **0.02**
across *both* calibration slices (in-domain 650 + external SPML 3,179); **never selected on test**.
Test slices: in-domain **1,257** (258 malicious / 999 benign) and the honest **external SPML 12,734**
(10,056 malicious / 2,678 benign). Data sha256: train `850d1372…`, external_test `eb82ce29…`.
Environment: system Python 3.14.6, torch 2.13.0+cpu, onnxruntime 1.31.1, 8 threads (v6 + corrected
v1 rows: 16 threads for scoring; latency is always single-thread ONNX).

| Model | Deployable in L4? | External SPML recall [Wilson 95%] | Ext FPR | Ext precision | In-domain recall* | p50 / p95 ms |
|---|---|---|---|---|---|---|
| **ProtectAI DeBERTa-v3 (rival)** | **No** — 184M params (>100M cap); p95 258 ms (>250 ms) | **0.883 [0.877–0.889]** | 0.0108 | 0.997 | 0.636 | 174.4 / 258.5 |
| **CHIMERA v6 MiniLM-L12 distilled (mine, new)** | Yes — 33.4M int8 | **0.588 [0.578–0.598]** | 0.0235 | 0.990 | 0.919 | 12.0 / 12.9 |
| TF-IDF + LogReg (baseline) | Yes | 0.350 [0.341–0.360] | 0.0273 | 0.980 | 0.895 | **0.41 / 1.11** |
| CHIMERA v4 (mine, prev) | Yes — 11.17M int8 | 0.214 [0.207–0.223] | 0.0149 | 0.982 | 0.764 | 5.09 / 8.68 |
| CHIMERA v5 (mine) | Yes — 11.17M int8 | 0.162 [0.155–0.169] | 0.0220 | 0.965 | 0.791 | 6.12 / 8.53 |
| CHIMERA v1 (deployed toy) — **corrected** | Yes — int8 | 0.002 [0.001–0.003] | 0.0000 | 1.000 | 0.085 | 0.77 / 1.49 |

\* In-domain recall is an **upper bound**, not generalization: origin-style leakage (ultrachat 0%
malicious, gandalf 100% malicious) lets a model score the *source style* instead of the attack. The
**external SPML slice is the honest one.** Thresholds: v6 ≈3e-6 (see the threshold note below), v5
0.9157, v4 0.9941, v1 0.7328 (corrected), ProtectAI 0.99994, TF-IDF 0.4810.

**Correction (v1 row).** The earlier v1 row (0.061 external / 0.008 in-domain) was **invalid**: v1's
directory ships only `vocab.txt`, and the harness fallback `BertTokenizerFast(vocab_file=...)`
silently builds a **5-token vocabulary (every token `[UNK]`)** under transformers 5. The harness now
builds the WordPiece tokenizer explicitly (`lowercase=True, strip_accents=False`, identical to the
Java `WordPieceTokenizer`: NFKC + lowercase, accents kept) and refuses to run if the tokenizer
vocabulary size differs from `vocab.txt`. Re-measured, v1 is even weaker (0.2% external, 8.5%
in-domain). v4/v5 rows loaded `encoder/` tokenizer configs (`strip_accents=false`) and are unaffected;
ProtectAI and TF-IDF rows are unaffected.

**Reading it honestly — this is a loss for my deployable models, and I am not spinning it.**
- **The market rival wins decisively on the honest slice.** ProtectAI DeBERTa-v3 reaches **88.3%
  external recall @ 1.08% FPR** — ~4× my best pre-distillation deployable guard (v4, 21.4%; v6 in
  §3.1 reaches 58.8%). It is the quality
  benchmark to beat. **But it is not deployable in L4:** 184M params (> the 100M cap) and **p95
  258 ms exceeds the 250 ms timeout** (p50 174 ms). It detects *prompt injection, not jailbreaks*
  (its in-domain recall is only 63.6% because that slice is jailbreak-persona heavy).
- **My new v5 REGRESSED vs v4 externally** (16.2% < 21.4%) and its external FPR **0.022 slightly
  exceeds the 0.02 budget** (calib→test shift). The fine-tune did not help; root causes are confirmed
  from `MANIFEST_V5.json` + `metadata.json`: **(1)** train is **7,346 benign / 2,266 malicious
  (3.24:1)** but v5 used `positive_weight=1.0`, systematically under-scoring injection; **(2)**
  `max_length=128` head-truncates long SPML persona attacks (2,124 train rows truncated; V5_DESIGN G3:
  54% of misses are out-of-window); **(3)** only **2 epochs**, loss still falling (0.370→0.202).
- **A trivial TF-IDF+LogReg baseline beats BOTH my fine-tuned bert-mini guards externally** (35.0% vs
  21.4%/16.2%; the distilled v6 in §3.1 now beats it at 58.8%).
  This is the most important signal: the task is *not* impossible at <100M — **my fine-tune is
  suboptimal**, with clear headroom. Lexical cues generalize to SPML better than my under-trained,
  positively-under-weighted, truncated bert-mini.
- **Latency:** my int8 ONNX guards are 5–6 ms p50 (far under 250 ms); TF-IDF 0.4 ms; ProtectAI
  174/258 ms. Speed is not my problem — **external recall is**.
- **G1 (SPML-native recall ≥50% @ FPR≤2%) is NOT met** by any deployable model here (v6 reaches
  40.9% native, below). v1 (the currently deployed toy) is near-useless externally (0.2%, corrected)
  and in-domain (8.5%) — it should be replaced.

### 3.1 v6 — knowledge distillation from the rival, trained on the RX 9070 XT (measured)

Approach (from `build-check/l4_claude/distill_l4.py`; `l4_gemini` notes reviewed): distil the
non-deployable ProtectAI DeBERTa-v3 teacher into a deployable <100M student so its external
generalization is inherited while the L4 runtime contract (WordPiece `vocab.txt`, opset 17
dynamic-int8, `input_ids/attention_mask/token_type_ids` → `logits[B,2]`) is kept.

- **Hardware:** teacher scoring and student training ran on **AMD Radeon RX 9070 XT (gfx1201, 16 GB)
  via ROCm on Windows** (`torch 2.13.0+rocm10.1.0`, separate `build-check/rocm-venv`; system torch
  untouched). `TORCH_BLAS_PREFER_HIPBLASLT=0` is required (AMD known issue for RX 9070 training).
  Teacher scoring ≈265 rows/s on GPU vs 15–20 rows/s on 16 CPU threads; MiniLM training 0.10 s/step,
  12 epochs ≈15 min. Vulkan is not a PyTorch training backend and was not used.
- **Data (no eval slice, no SPML):** v5 train (9,612) + `transfer_extra.jsonl` (13,262: in-the-wild
  regular/jailbreak, codesagar_v3 ultrachat/jackhhao/deepset), built by
  `build-check/l4_distill/build_transfer.py` with normalized-text exclusion of every v5
  train/calib/test/external row. `raw/spml/` is the external slices' source and is **excluded**.
  `--forbid-overlap-with` both test files is enforced by the trainer. 22,874 rows, 2,865 pos.
- **Loss:** `α·CE(weight=[1, w+]) + (1−α)·BCE(s/T, σ(t/T))·T²`, α=0.5, T=3, `w+`=6.98 (auto, class
  ratio), teacher logits centred on its operating point logit(0.99994); hard labels only on
  `jailbreak` sources (the teacher card: "does not detect jailbreak attacks") and on rows where the
  teacher disagrees with the label (3,033 rows hard-only).
- **Student:** `microsoft/MiniLM-L12-H384-uncased`, 33.36M params, max_length 128, lr 8e-5, batch 32,
  bf16 autocast, 12 epochs; **epoch 8 selected by mean calibration recall** (never test).
  `bert_medium` (6 epochs) was worse on external calib than MiniLM at the same budget (0.42 vs 0.49;
  both from the pre-tokenizer-fix runs).
- **Calibration (int8):** in-domain calib recall 0.953 @ FPR 0.020; external calib recall 0.571 @
  FPR 0.016.

Per-source external test (same calibration threshold; ProtectAI scored at its 0.99994 threshold):

| SPML subset | rows | v6 (mine) | ProtectAI (rival) |
|---|---|---|---|
| native malicious (recall) | 6,731 | 0.409 | 0.827 |
| gandalf malicious (recall) | 3,325 | 0.924 | 0.999 |
| native benign (FPR) | 2,678 | 0.023 | 0.011 |

**Reading it honestly.**
- **v6 is my best deployable guard by a wide margin:** external recall 0.588 vs 0.214 (v4), 0.162
  (v5), 0.350 (TF-IDF) — 2.7× v4. It reaches 67% of the rival's external recall (0.588 / 0.883) with
  18% of its parameters and 12 ms single-thread p50 (vs 174 ms).
- **It still loses to the rival**, especially on SPML-native attacks (0.41 vs 0.83). **G1 remains
  unmet.** The gandalf subset (0.92) is inflated: Lakera gandalf rows are in train, and ProtectAI's
  card lists 8 *unnamed* MIT datasets (gandalf is MIT), so gandalf may also leak through the teacher.
- **FPR budget missed on test:** 0.0235 external / 0.025 in-domain vs the 0.02 budget chosen on
  calibration (calib→test shift; CI 0.018–0.030). Deploy with a slightly stricter cut or re-calibrate
  on a larger benign slice before claiming ≤2%.
- **Threshold note:** the centred teacher offset pushes student probabilities very low, so the
  operating cut is ≈3e-6 in probability (≈ −12.7 logit margin). That is valid but fragile to display/
  rounding; production should compare the raw `logit[1]−logit[0]` margin, or fold the offset into
  the classifier bias before export. The JSON stores the threshold rounded to 6 decimals, which moves
  native FPR 0.0235→0.0232 in my per-source re-score.
- **Int8 drift:** dynamic quantization moves the margin by up to ≈2.4 logits vs fp32 (fp32 ONNX =
  torch exactly); all reported numbers are the **int8** artifact actually deployable.
- **Tokenizer fix applied before this run:** the first MiniLM/bert_medium runs used the HF default
  `strip_accents` (≠ Java runtime); students now carry the production `l4_base` tokenizer config
  (0 token mismatches on 3,000 external rows vs the fallback/Java-equivalent tokenizer).

Artifacts (not committed): `build-check/l4_distill/out_minilm_l12_v2/` (`model.onnx` int8,
`model_fp32.onnx`, `vocab.txt`, `metadata.json`), benchmark `build-check/l4_distill/bench_v6/`.

### 3.2 Gemini recipe vs Claude recipe (v6), and Gemini's TF-IDF stacker (measured)

`build-check/l4_gemini/train_l4_gemini_distill.py` is a bug-fixed port of Gemini's §3 loss:
- weighted cross-entropy (α 0.35, positive weight 3.2);
- centred-teacher KL (T 3, scale 2.5) with the "do-no-harm" mask;
- 768-d hidden-state cosine alignment through a training-only projection;
- benign-margin hinge.

Setup: same MiniLM-L12 student, same ProtectAI teacher, same RX 9070 XT. The variants are:
- **A**: Gemini as written. v5 train only, 5 epochs, lr 3e-5, batch 16, last epoch kept.
- **B**: apples-to-apples with v6. v5 train + transfer_extra, 12 epochs, lr 8e-5, batch 32, epoch
  selected on calibration.

Comparison harness: `build-check/l4_gemini/compare_students.py`. It uses the same worst-case
calibration threshold, an unrounded cut, int8 ONNX, and the locked slices.

The stacker feeds student logit + TF-IDF logit into a logistic regression. It is **cross-fitted**:
5-fold out-of-fold calibration scores choose the threshold, so the threshold is never picked on data
the stacker was fit on.

| Model | in-dom recall | in-dom FPR | ext recall | ext FPR | SPML native | SPML gandalf |
|---|---|---|---|---|---|---|
| **v6 (Claude recipe)** | **0.919** | 0.025 | 0.588 | 0.0235 | **0.421** | 0.925 |
| v6 + TF-IDF stacker | 0.930 | 0.019 | **0.601** | 0.0273 | 0.433 | 0.940 |
| **Gemini B (Gemini loss, v6 data/schedule)** | 0.880 | **0.009** | **0.591** | 0.0243 | 0.412 | **0.953** |
| Gemini B + stacker | 0.880 | 0.009 | 0.567 | 0.0228 | 0.378 | 0.950 |
| Gemini A (as written) | 0.857 | 0.007 | 0.279 | 0.0306 | 0.094 | 0.654 |
| Gemini A + stacker | 0.899 | 0.006 | 0.346 | 0.0265 | 0.107 | 0.830 |
| ProtectAI rival (§3.1) | — | — | 0.883 | — | 0.827 | 0.999 |

**Reading it honestly.**
- **Neither recipe beats the other.** Gemini B and v6 tie on external recall (0.591 vs 0.588).
  Gemini B is lower on in-domain recall (0.880 vs 0.919) and lower on native (0.412 vs 0.421), but
  has a much cleaner in-domain FPR (0.009 vs 0.025). Gemini's extra loss terms buy in-domain
  precision, not SPML-native recall.
- **Gemini as written (A) is undertrained.** It uses 5 epochs at lr 3e-5 on v5 train only. External
  recall collapses to 0.279, and native to 0.094.
- **The stacker is not a clean win.**
  - On v6 it adds +0.013 external recall but pushes external test FPR to 0.027, over budget.
  - On Gemini B it hurts.
  - It would also need TF-IDF in the Java runtime.
  - Not adopted.
- **v6 stays the shipping candidate.** Neither recipe meets G1 (native ≥ 0.50), and neither gets
  close to the rival (0.83 native). The remaining gap is data, not loss design.

### 3.3 Two-model ensembles (measured, not adopted)

Harness: `build-check/l4_gemini/compare_students.py --ensemble A+B`. The protocol is the same as
§3.2: one threshold per fused score by worst-case FPR ≤ 0.02 on both calibration slices, int8 ONNX,
locked slices. Two fusions are tested:
- **mean-logit**: σ((logit pA + logit pB) / 2).
- **Gemini max-fusion**: max(0.55·pA + 0.45·pB, 0.92·max(pA, pB)).

Outputs: `build-check/l4_gemini/ensemble.json`, `build-check/l4_v7/compare.json` and
`compare_v7b.json`.

| Model / ensemble | in-dom recall | in-dom FPR | ext recall | ext FPR | SPML native | SPML gandalf |
|---|---|---|---|---|---|---|
| v6 alone (reference) | 0.9186 | 0.025 | 0.5879 | **0.0235** | 0.4213 | 0.9251 |
| v6 + Gemini B, mean-logit | 0.9186 | 0.016 | 0.6130 | 0.0265 | 0.4475 | 0.9480 |
| v6 + Gemini B, max-fusion | 0.8953 | 0.010 | 0.5942 | 0.0258 | 0.4167 | 0.9534 |
| v6 + v7, mean-logit | 0.9186 | 0.024 | **0.6239** | 0.0261 | **0.4629** | 0.9498 |
| v6 + v7, max-fusion | 0.9186 | 0.023 | 0.5803 | 0.0273 | 0.4017 | 0.9417 |
| v6 + v7b, mean-logit | 0.9186 | 0.028 | 0.6146 | 0.0243 | 0.4494 | 0.9489 |
| v6 + v7b, max-fusion | 0.9109 | 0.027 | 0.5577 | 0.0224 | 0.3704 | 0.9368 |
| v7 + Gemini B, mean-logit | 0.9186 | 0.014 | 0.5689 | 0.0246 | 0.3849 | 0.9414 |
| v7 + Gemini B, max-fusion | 0.9109 | 0.012 | 0.6010 | 0.0284 | 0.4246 | **0.9582** |
| v7b + Gemini B, mean-logit | 0.8798 | 0.020 | 0.5683 | 0.0232 | 0.3834 | 0.9426 |
| v7b + Gemini B, max-fusion | 0.9031 | 0.020 | 0.5896 | 0.0239 | 0.4096 | 0.9540 |

**Reading it honestly.**
- The best ensemble, v6 + v7 mean-logit, lifts external recall from 0.588 to 0.624 and native from
  0.421 to 0.463. That is the largest native gain measured so far.
  - It also raises external FPR from 0.0235 to 0.0261.
  - It still misses G1 (native ≥ 0.50).
- Every ensemble that raises external recall also raises external FPR above v6's 0.0235.
  - Two ensembles have a lower external FPR: v6 + v7b max-fusion (0.0224) and v7b + Gemini B
    mean-logit (0.0232).
  - Both lose external recall (0.558 and 0.568).
- Two students double L4 inference cost (2 × 12–18 ms p50), and the Java runtime would have to load
  two models.
- **Not adopted.** No ensemble beats v6 on external and native recall without a worse external FPR.
  The v6 + v7 mean-logit pair is the option to revisit once a larger benign calibration slice
  allows a tighter FPR cut.

### 3.4 v7 / v7b: research datasets + persona generator, retrained on the RX 9070 XT (measured, not adopted)

v7 keeps the v6 recipe unchanged and only grows the transfer set. The new rows are teacher-scored
by ProtectAI on the GPU, exactly as in v6. Recipe (`build-check/l4_v7/run_v7.sh`):
- MiniLM-L12, 12 epochs, lr 8e-5, batch 32.
- α 0.5, T 3, teacher threshold 0.99994.
- Hard labels only on `jailbreak` sources; `--positive-weight auto`.
- ROCm, 16 threads, amp.

**Final training-set record (v7 extra).**
- Built by `fraud-gate/training/build_l4_v7_corpus.py`.
- Output: `datasets/new_custom_datasets/out/v7/l4_v7_extra.jsonl` plus `MANIFEST_V7.json`.
- 16,893 rows (10,906 malicious / 5,987 benign), sha256 `2f1a5654…5a485436`, seed 7.
- The manifest stores the sha256 of every raw input file.

| Source | Licence / paper | Malicious | Benign | What was taken |
|---|---|---|---|---|
| neuralchemy/Prompt-injection-dataset (includes a HackAPrompt subset) | Apache-2.0 | 2,575 | 1,681 | Non-augmented rows: v1 1,030/1,534, hackaprompt 1,382/0, original 79/20, wildguard 84/127 |
| BIPIA indirect injection | CC-BY-SA-4.0, arXiv 2312.14197 (HF mirror) | 2,376 | 1,146 | Code/email/table windows. Each positive is paired with the same window minus `attack_str` |
| Microsoft LLMail-Inject phase 2 | MIT, arXiv 2506.09956 | 2,955 | 160 | Judge/API-confirmed attack emails ≤ 700 chars, plus the official false-positive emails |
| persona_gen (generated here) | Taxonomy from SPML 2402.11755, Tensor Trust 2311.01011, HackAPrompt 2311.16119 | 3,000 | 3,000 | 10 role-bot attack tactics, each with benign counterfactuals that reuse the same personas, openers and trigger words |

Hygiene:
- **Dropped:** 1,366 duplicates, 130 rows already in the v6 transfer set, 5 rows overlapping eval.
- **Forbidden, never trained on:**
  - v5 slices: calib 650, test 1,257, external_calib 3,179, external_test 12,734, external_full
    15,913.
  - SPML user prompts: 16,011.
- **Dedupe:** exact normalized text and 64-char normalized prefix against eval + SPML; exact text
  against v5 train + v6 transfer.
- **Excluded:** Tensor Trust, because its HF card states no data licence.

| Run | Training rows | pos / neg | positive weight | hard-only rows | Epoch (chosen on calib) | int8 p50 / p95 / max, 90 longest inputs |
|---|---|---|---|---|---|---|
| v7 = v6 transfer (22,874) + v7 extra | 39,767 | 13,771 / 25,996 | 1.89 | 10,395 | 6 | 17.8 / 22.0 / 23.6 ms |
| v7b = v7 minus all 6,637 BIPIA + LLMail rows (ablation) | 33,130 | 8,440 / 24,690 | 2.93 | 5,615 | 7 | 13.8 / 17.5 / 18.2 ms |

Results on the locked v5 slices (`compare_students.py`; logs `build-check/l4_v7/compare*.log`):

| Model | in-dom recall | in-dom FPR | ext recall | ext FPR | SPML native | SPML gandalf |
|---|---|---|---|---|---|---|
| **v6 (shipping candidate)** | **0.9186** | 0.025 | 0.5879 | **0.0235** | 0.4213 | 0.9251 |
| v7 | 0.9109 | **0.021** | 0.5737 | 0.0302 | 0.3979 | 0.9296 |
| v7b | 0.8953 | 0.025 | **0.5990** | 0.0288 | **0.4326** | **0.9359** |

**Reading it honestly.**
- **v7 is worse than v6** on external recall (0.574 vs 0.588), native (0.398 vs 0.421) and
  external FPR (0.030 vs 0.0235). Adding 16.9k research and generated rows did not move the honest
  slice.
- **The v7b ablation isolates the cause.** Removing BIPIA and LLMail makes v7b beat v6 on external
  recall (+0.011) and native (+0.011). It still fails the adoption rule:
  - external FPR 0.0288 vs 0.0235;
  - in-domain recall 0.895 vs 0.919.
- **Likely reason (not proven):** BIPIA and LLMail are *indirect* injection corpora (an attack
  embedded in an email, table or code). SPML attacks are *direct* role-bot prompts.
- **Not adopted.** More public data of this kind does not close the gap to the rival (0.83 native).
  The missing ingredient is labelled direct role-bot attacks; the gated sets listed in §9 are the
  nearest candidates.
- Artifacts (not committed): `build-check/l4_v7/out_v7/`, `out_v7b/`, teacher scores and logs.

---

### 3.5 v8: guarded v6 replay + new ProtectAI-scored data (2026-11-16, NOT ADOPTED)

**Implementation and training.** `fraud-gate/training/prepare_l4_v8_data.py` builds a bounded transfer set from the uploaded HackAPrompt and web-attack CSV files. Only successful, non-error HackAPrompt attempts are positive; only `Label=0` web rows are benign. Failed attacks are excluded, never relabelled benign. Normalized exact text, digit-normalized 96-character prefix groups, and actual 128-token windows are excluded against replay/locked evaluation; new train/calibration/test groups are disjoint. Each source contributes 1,500 training, 500 calibration and 500 test rows. Prefix groups are a heuristic, not proof of author/template independence. The strong source-to-label correlation makes the new split easier than a source-balanced real-world benchmark.

The student starts from **v6**, retains **all 22,874 replay rows**, and adds **3,000 rows scored by the local ProtectAI DeBERTa-v3 teacher** (25,874 total; 4,365 positive). ProtectAI is an offline teacher, not an added live service. MiniLM-L12-H384 remains 33,360,770 parameters with the same 30,522-token vocabulary. ROCm/RX 9070 XT training used four epochs, batch 32, learning rate 5e-6, seed 13, mixed precision, α=0.5/T=3 and automatic positive weight 4.93. HackAPrompt/jailbreak rows remain hard-label-only; teacher disagreements also use hard labels. Epoch **3** was selected on the two existing calibration sets only.

The first training attempt exposed a loader bug: the old calibration files use `payload`, which the helper ignored. That run produced empty calibration/NaNs and **no candidate**. The helper now accepts `payload` and rejects empty/single-class calibration; corrected training/export passed. The failure log is retained, and the payload/Unicode regression test passes locally.

**Uploaded DeepSeek suggestions.** Grouped sampling and conservative evaluation were incorporated. Resplitting external calibration into training and fitting a supervised stacker on SPML calibration were rejected. TF-IDF/XGBoost and BiGRU voters were not promoted based on metadata alone: they would require separate leakage-safe training, real 128-token handling, Java integration and parity/latency evidence. Neither SPML nor locked test rows were added to training.

**Frozen paired protocol.** `fraud-gate/training/evaluate_l4_v8.py` evaluates both int8 models at batch 1 with fixed 128-token padding, single-thread CPU ONNX Runtime and the same tokenizer. Each model gets **one full-precision margin cutoff** calibrated to worst-case FPR ≤2% across **three** calibration sets (old internal, old external, new). The cutoff is written to `calibration_lock.json` before holdout scoring. v6 cutoff = **−3.652773857116699**, v8 = **−3.697270154953003**, prediction `logit[1]−logit[0] > cutoff`. The evaluator refuses an already locked experiment. Historical holdouts are reused for regression comparison; they are not newly unseen data.

| Holdout | Positive / benign rows | v6 recall | v8 recall | v6 FPR | v8 FPR |
|---|---:|---:|---:|---:|---:|
| Old internal | 258 / 999 | 80.62% (208) | 86.82% (224) | 0.20% (2) | 0.80% (8) |
| Old external SPML | 10,056 / 2,678 | 12.25% (1,232) | 27.83% (2,799) | 0.22% (6) | 0.86% (23) |
| New grouped sources | 500 / 500 | 46.00% (230) | 97.60% (488) | 2.60% (13) | **3.60% (18)** |

Counts in parentheses are true/false positives. Full Wilson intervals, ROC-AUC and average precision are in the JSON report. New-holdout v8 FPR 95% Wilson interval is **2.29–5.62%**, subject to the row-independence caveat. External ROC-AUC **regressed 0.92477 → 0.88618**, despite improved recall at these particular cuts. New-source recall alone does not establish better generalization.

**Do not compare the 12.25% v6 row directly to historical 58.8% (§3.1).** The additional benign calibration distribution imposes a much stricter common operating policy, and fixed-padding/batch-1 inference is explicit here. Historical numbers are retained with their original protocol; no artifact was replaced to obtain this comparison.

A descriptive source breakdown from saved predictions, without new inference or threshold tuning, gives SPML-native malicious recall **3.68% v6 / 7.81% v8** (248/6,731 vs 526/6,731), far below G1's 50% requirement. The mixed external slice also contains 3,325 gandalf attacks, which are easier and do not establish native SPML quality. Full Java/runtime G1 remains **NOT_MEASURED** for v8 because offline promotion already failed.

**Runtime checks.** Both artifacts pass ONNX checking, opset 17 and dynamic int64 `[B,L]` input-contract checks, vocabulary equality and finite `[1,2]` output checks. Tokenization plus int8 ONNX P50/P95: v6 **12.71/13.30ms**, v8 **12.53/13.31ms** (200 single-row synthetic longest-window calls, 25 warmups, one CPU thread; measured after the training process finished). This is not Java end-to-end latency. Trainer-reported int8/PyTorch calibration decision agreement is **98.17%**, not exact parity; mean absolute margin difference 0.4525. Thresholds must be calibrated on the deployed int8 form, not copied from PyTorch or rounded.

**Decision: DO NOT PROMOTE.** The candidate passes the paired recall and CPU gates, but fails the required ≤2% FPR gate, increases FPR on every holdout, and misses the native quality requirement. No further tuning on these exposed holdouts was performed. v6 remains the best prior-protocol candidate; neither v6 nor v8 is claimed production-ready. The pre-existing deployed L4 model is untouched.

Evidence (local, not committed): `build-check/l4_v8/{protocol.json,data_manifest.json,calibration_lock.json,paired_evaluation.json,external_subset_diagnostic.json,train_corrected.log}` and saved prediction arrays. Candidate int8 SHA256 `564804579b6b1eddca1bfb58f2337c3aea394a6116c3b0535bdb3724eb2e414b`; v6 `8d7aff300c9adf9e2f219757b2a832b954730fd3ccda70fe513170bcbf5bf8da`. Candidate artifacts remain isolated in `build-check/l4_v8/out_v8/`. Dataset/protocol hashes are recorded; raw data/model redistribution licences still require review.

### 3.6 v9: Qwen dual-view + reliability-gated KD + grouped lexical stacker (2026-11-16, NOT ADOPTED)

**What was built.** An isolated v9 candidate initialized from the corrected **v8** checkpoint (MiniLM-L12-H384, 33,360,770 params), adapting the Qwen proposal in `build-check/new_qwen_l4/` rather than executing it unchanged. Two views share one encoder: **A** = `[CLS] payload [SEP]` fixed 128; **B** = `[CLS] system≤96 [SEP] payload [SEP]` fixed 192 with real segment ids (0/1). Training loss = positive-weighted CE + reliability-gated KD (ProtectAI + v6-retention teachers, per-view/per-slice calibrated offsets, sign-contradiction and jailbreak-source gating, v6 silenced on B) + cosine alignment to ProtectAI CLS (projection discarded at export) + margin hinge, with quant-noise and per-batch 50% segment dropout on B. A TFIDF(1–3gram,50k)+LR lexical branch is fit on **train only**; a 5-fold **GroupKFold** XGBoost stacker (300 trees, depth 3, monotone on `m_a,m_b,lex_logit`, NaN-missing B) is fit on a **training-side meta split only** — never on SPML or locked calibration labels. The unconstrained `m_b−m_a` feature from the upload was removed.

**Leakage/runtime fixes vs the upload.** Reversed teacher pair order corrected (system first); real B segment ids kept during ONNX scoring; context-dependent synthetic labels never assigned to view A (`label_a=None`); stacker fit on meta not pooled calibration; strict GroupKFold with no row-split fallback; exact + Unicode-letter-skeleton + visible-window dedup; high-level HackAPrompt families reserved before lower-level sampling. Eleven focused helper tests pass (`fraud-gate/tests/test_l4_v9.py`).

**Data (locked, `data_manifest.json`).** Train 30,788 (23,367 neg / 7,421 pos): v8 replay minus 2,971 rows dropped by the stronger overlap guard, plus 3,500 new HackAPrompt attempts (levels 0–6, all attempts labelled attack-intent), 3,500 No Robots benign instructions, 15 curated prompts.chat personas, 6 authored benign imperatives, 864 authored topic/rule pairs. Meta 1,294; new calib 1,004 (Hack levels 7–8 + benign); new test 1,005 (Hack level 9 + benign); paired calib/test 288 each. 61,390 Hack rows excluded as prior v6/v8 exposure; 2,099 cross-level families excluded. **No Robots is CC-BY-NC-4.0 → research-only, not commercially cleared.** Synthetic pairs are assistant-authored templates, not independent LLM generations or human-reviewed SPML. Prompt Guard and XSTest are gated and were not used.

**Training/export.** ROCm RX 9070 XT, bf16, 4 epochs, best **epoch 2** by mean calibration recall (0.635). int8 ONNX 33,941,565 bytes, SHA256 `499846378652f664752cd4fe2a61cf6be1fa033455fcf6c7a052931f9214f0a5`, opset 17, dynamic int64 `[B,L]`, vocab identical to v6/v8. **Export caveat:** the ROCm and system-CPU torch exporters trace the eager attention mask differently; the CPU-exported graph failed eager parity, so the graph was exported under ROCm and **FP32 eager parity verified separately under system-CPU torch** (max abs margin error ≈4.8e-6 A / 4.4e-6 B, `export_parity.json`). int8 mean abs margin drift 0.525 A / 0.489 B (max 12.6 A on one outlier row); thresholds are calibrated on int8 scores, not copied from FP32.

**Locked protocol (`protocol.json`).** Calibration FPR budget 1% per view, worst-case across slices; test gate ≤2%. Cuts chosen on calibration only, holdouts scored once. Baselines v6/v8 and ProtectAI use the same five calibration slices (internal, external, v8new, v9new, paired) with payload-only A scores; v9 also reports A-only, B-only and the hybrid stacker. ProtectAI rival scored **GPU bf16 batch32** (cached), not int8, and is excluded from the 250ms latency gate. External B view uses SPML system prompts recovered by row id.

**Holdout results (recall / FPR; int8 ONNX batch-1 single-thread for students):**

| Slice | v6 | v8 | v9-A | v9-hybrid | ProtectAI-A |
|---|---|---|---|---|---|
| internal (258+/999−) | .632 / .0010 | .857 / .0060 | .826 / .0070 | .663 / .0020 | .609 / .0000 |
| external SPML (10056+/2678−) | .037 / .0004 | .210 / .0078 | .116 / .0071 | .024 / .0019 | **.968 / .0078** |
| v8new (500+/500−) | .274 / .0140 | .972 / .0220 | .992 / .0200 | .976 / .0040 | .996 / .0000 |
| v9new (500+/505−) | .028 / .0020 | .946 / .0099 | .938 / .0079 | .454 / .0000 | .828 / .0000 |
| paired synthetic (144+/144−) | .000 / .0000 | .000 / .0000 | .000 / .0000 | .000 / .0000 | .000 / .0000 |

External ROC-AUC: v6 .925, v8 .886, v9-A .905, v9-hybrid .820, ProtectAI .997. Wilson95 external recall: v8 [.202,.218], v9-A [.110,.122], v9-hybrid [.022,.028]. v9-hybrid v9new recall CI [.411,.498].

**Paired/B view did not work.** v9-B paired recall .035 (AUC .567); ProtectAI-B on external has **FPR .9675** (flags nearly everything when a system prompt is present) and paired recall .028. No model learned the authored in-domain vs out-of-domain rule task (paired recall ≈0 for all). The dual-view paired concept, as implemented here, provides no usable signal.

**Stacker overfits meta.** GroupKFold OOF AUC .955 / recall .742 on meta, but the hybrid **loses recall on every real holdout** vs v9-A (external .116→.024, v9new .938→.454, internal .826→.663) while pushing FPR toward zero. Monotonicity on `m_a`/`lex_logit` verified; NaN-B branch finite. The lexical/stacker branch trades away too much recall for FPR and does not generalize beyond the meta distribution.

**Latency (200 single-row calls, 25 warmups, one CPU thread).** tokenize+int8 P50/P95: v6 12.05/13.17ms, v8 11.99/12.23ms, v9-A 12.44/13.17ms; v9-B ONNX-only 18.43/19.23ms. The hybrid adds lexical+XGBoost overhead (not separately timed end-to-end) and is **not implemented in the Java runtime** — not a drop-in deployment.

**Gates (v9-hybrid as the proposed candidate):** all-holdout FPR≤2% **PASS**; CPU P95<250ms **PASS**; no recall regression vs v8 **FAIL**; no recall regression vs v6 **FAIL**; higher mean recall vs v8 **FAIL**. **Offline candidate passed: FALSE.**

**Decision: DO NOT PROMOTE.** The Qwen hybrid does not beat v8 or v6 overall; the stacker and paired view degrade real-holdout recall. The plain neural **v9-A beats v6 on every holdout** and matches/beats v8 on internal/v8new/v9new, but still trails v8 on external SPML (.116 vs .210) and trails v6 external ranking (.905 vs .925). **ProtectAI remains far superior on external SPML recall (.968)** at comparable FPR; the 33M student does not close that gap. v6 remains the best prior-protocol deployable student; v8 and v9 are not adopted. No deployed/baseline artifact changed (v6 `8d7aff…`, v8 `564804…`, deployed `6c4e95…` re-verified). No tuning on exposed holdouts. Research-only licence and missing Java hybrid integration independently block promotion regardless of metrics.

Evidence (local, not committed): `build-check/l4_v9/{protocol.json,data_manifest.json,training_result.json,export_result.json,export_parity.json,evaluation.json,train.log,evaluation.log,protectai_gpu.log}` and saved prediction arrays. Scripts: `fraud-gate/training/{l4_v9.py,prepare_l4_v9_data.py,train_l4_v9.py,score_protectai_v9_gpu.py,evaluate_l4_v9.py}`.

### 3.7 v10: obfuscation augmentation + multi-view measurement + canary loop (2026-11-16, NOT ADOPTED)

This round tested the six proposals in `build-check/new_l4_claude/` (obfuscation matrix, balanced augmentation, HackAPrompt pair prep, canary guard, known-answer second opinion, scope-conditioned detection). **Headline: obfuscation tricks do not close the external-recall gap; the missing ingredient is labelled direct *polite scope-violation* data, which the 128-token single-view L4 contract cannot yet exploit.** v6 remains deployed and unchanged.

**Obfuscation matrix (measured, `build-check/l4_obf_measure/`).** 23 transforms applied to a 250-per-label subsample of `external_calib` (11,500 matrix rows), scored with the deployed v6 int8 artifact at its operating cut (margin −12.6115). Benign rows get the *same* transforms to expose the "looks-encoded ⇒ malicious" shortcut. Two scoring modes: **raw** (encoded view only) and **multi-view max-pool** (raw + up to 8 decoded views via `canary_guard.derived_views`, mean 4.85 views/row).

| Transform | Raw recall / FPR | Multi-view recall / FPR | Note |
|---|---|---|---|
| identity (plain) | 0.520 / 0.016 | 0.648 / **0.396** | multi-view FPR explodes even on plain benign |
| bury_after_filler | **0.000** / 0.000 | 0.312 / 0.300 | real blind spot; partial recovery, high FPR |
| url_encode | **0.008** / 0.000 | 0.928 / **0.848** | real blind spot; recovery unusable (FPR) |
| rot13 | 0.056 / 0.088 | 0.692 / 0.424 | blind spot |
| reverse_chars | 0.268 / 0.316 | 0.648 / 0.396 | |
| caesar3 (held-out) | 0.352 / 0.172 | 0.404 / 0.296 | |
| hex | 1.000 / **0.984** | 1.000 / 1.000 | v6 already flags encoded *benign* |
| spaced_letters | 1.000 / **0.996** | 1.000 / 1.000 | encoded-benign shortcut |
| html_entities (held-out) | 1.000 / **1.000** | 1.000 / 1.000 | encoded-benign shortcut |
| code_comment | 0.824 / **0.880** | 0.916 / 0.964 | encoded-benign shortcut |

**Conclusion:** v6 has genuine blind spots (burial, url-encode, rot13) but *also* over-flags encoded benign text (hex/spaced/html FPR ≈ 1.0). Multi-view max-pool recovers recall (identity .520→.648, url-encode .008→.928, burial 0→.312) but pushes FPR to **0.396 on plain benign and ≈1.0 on encoded benign** — far above the 2% gate. **Multi-view is NOT deployable**; it amplifies the very shortcut Claude's module warned about. The ONNX guard scores the raw view only; adding decoded views at runtime would inherit this FPR.

**v10 balanced-augmentation candidate (measured, NOT ADOPTED).** To test whether *training* on obfuscation (both labels at the same rate, so "encoded" is not taught as "malicious") helps, v10 = v6 teacher-scored replay (22,874 rows) + 15 TRAIN transforms at p=0.30, seed 13 (29,746 rows; neg aug rate 0.3012, pos 0.2949). The 7 held-out transforms (caesar3, reverse_words, html_entities, payload_split, json_field, multilayer, hyphen_split) were excluded from training to measure zero-shot generalization. Trained on the ROCm RX 9070 XT, bf16, 14 epochs, **correct v6 base** `build-check/students/minilm_l12` (33,360,770 params), select-by recall under worst-case calib FPR ≤ 2%.

> **Base-confound correction.** A first v10 run accidentally used `build-check/l4_base` (11M, 4L/256H) instead of the v6 base (33M, 12L/384H); its external recall .286 was confounded by the smaller base and is **not** a clean test. The result below is the corrected run on the proper v6 base (`build-check/l4_v10/out_minilm/`, version `v10-obf-minilm`).

Selected **epoch 10** (fp32 eager, calibration only): internal recall **0.9333** / FPR 0.0200 / AUC 0.9833; external_calib recall **0.3356** / FPR 0.0187 / AUC 0.8231. Later epochs did not recover external recall (ep11 .334, ep13 .344, ep14 .342). **Even on the correct base, obfuscation augmentation *regresses* external recall from v6's .587 to ~.34** at comparable FPR. Higher epochs lowered training loss (0.82→0.54) but did not improve held-out fraud recall — the augmentation teaches encoding-invariance that trades away discrimination on real external attacks. **Gate (better recall, FPR ≤ 2%): FAIL. v10 NOT adopted; v6 unchanged.**

**int8 ONNX operating point (calibration only, batch-1 single-thread; `out_minilm/metadata.json`).** Threshold P ≥ **9.2918e-06** (margin −11.5864), max calib FPR 2%. Internal recall **0.9467** / FPR 0.0200 / AUC 0.9902; external_calib recall **0.3598** / FPR 0.0187 / AUC 0.8322 — still far below v6 int8 external recall .573. Latency p50 **11.53 ms** / p95 11.74 / max 11.89 (n=90); int8 parity mean abs margin drift 0.4506, decision agreement 0.9666. Artifact `model.onnx` 33.9 MB, SHA256 `33ee0aaa1ab4ffbdc65bf789a9b52d29c0fef777e418bd690da9ec487c8b970c`, opset 17, vocab SHA `07eced37…` identical to v6, base `build-check/students/minilm_l12`, 33,360,770 params. Latency passes but recall fails; **not promoted**.

**HackAPrompt pair data (prepared, not trained into a deployable model).** `build-check/sample_hackaprompt.py` reservoir-sampled 77,936 correct attempts; `build-check/l4_pair_data/` holds a leakage-safe pair corpus (hap_train 13,765 / calib 1,717 / test 1,693) with hard negatives from a 7,346-row benign pool, cluster-split, and a normalized `forbidden_eval_texts.jsonl` (18,660 rows = all v5 eval payloads + SPML system/user prompts) fixing an overlap-guard key bug (eval files use `payload`, SPML uses `User Prompt`/`System Prompt`, neither in the module's default TEXT_KEYS). 0 exact overlaps. **The principled pair route (`[template; input]` with real `token_type_ids`) needs >128 tokens and Java system-prompt prepending — a contract change.** The earlier v9-B paired view already failed (recall ≈ 0, ProtectAI-B external FPR .9675), so no compromised pair model was run. Documented as future work requiring a contract revision.

**Canary labeling loop (implemented, operator-enabled, default OFF).** `fraud-gate/app/canary_guard.py` (stdlib-only, copied from Claude's module) issues a fresh HMAC token per LLM call, plants it in the instruction, and scans backend output through derived encodings. A confirmed leak ⇒ the LLM argument is **discarded**, the informational delta **forced to 0**, the case **escalated**, and the inbound text harvested as a free labelled positive (`CANARY_HARVEST_PATH`). Wired into `debate.py` (`DebateResult.canary_escalated`) and `worker.py` (`chimera_fraud_gate_canary_escalations_total`). Enabled only when `CANARY_SECRET` ≥ 16 bytes is set in the environment (never in the repo); otherwise the guard is `None` and behavior is unchanged. It does **not** catch polite scope violations (nothing leaks). 14 tests pass (`test_canary_debate.py` + suite). The ±0.05 async cap and escalate-only invariants are preserved.

**Known-answer second opinion (recommendation only).** Async known-answer detection misses 30–50% and can reach FPR 0.1; recommended only as a borderline-band second opinion, never a settlement input. Not wired as a primary signal.

**Scope-conditioned polite-injection detection (NOT built).** SPML G1 (native recall ≥ 0.50 @ FPR ≤ 2%) remains **unmet** (v6 native ≈ 0.42). Closing it needs a scope-conditioned signal (pair model or in-scope intent gate) — blocked by the 128-token contract and the failed v9-B paired experiment. This is the honest open gap, not an obfuscation problem.

**UI.** The deployed L4 configuration (version, 33,360,770 params, 12L/384H base, vocab 30,522, max_length 128, 8,192-char cap, 250 ms timeout, opset-17 int8, inputs/outputs, operating threshold P ≥ 3.3335e-06 / margin −12.6115, FPR budget, teacher, distillation T/α, epoch selection, int8 parity, artifact SHAs, measured internal/external operating point, canary status, and the unmet-G1 / not-deployed caveats) is surfaced in the web "Labeled validation" page (`L4SemanticGuardPanel`, `web/src/App.jsx`).

Evidence (local, not committed): `build-check/l4_obf_measure/{obfuscation_report.json,matrix.jsonl,pred_raw.csv,pred_multiview.csv}`, `build-check/l4_v10/{v10_train.jsonl,v10_train.jsonl.meta.json,out_minilm/}`, `build-check/l4_v10_minilm_train.log`, `build-check/l4_pair_data/`. Scripts: `build-check/{measure_l4_obfuscation.py,sample_hackaprompt.py,assemble_v10_data.py}`, `fraud-gate/app/canary_guard.py`.

## 4. Credit brain — SYNTHETIC credit-boost/CPN data (NOT real-world quality)

Data: `datasets/synthetic_credit_boost/credit_apps.csv` (+ adaptive-seller holdout). Shared
`credit_brain.featurize` (34 features, no train/serve skew). Split: train 24,028 / val 7,944 /
test 8,028 (651 pos) / adaptive holdout 10,000 (741 pos). Harness:
`ai-brain/training/bench_credit_brain.py` → `benchmarks/credit/credit_benchmark.{json,md}`.

| Model | test ROC | test PR | adaptive ROC | adaptive PR | p50 ms |
|---|---|---|---|---|---|
| **LR (shipped, mine, stdlib)** | **0.9756** | **0.9595** | 0.9579 | 0.886 | **0.067** |
| HistGradientBoosting | 0.9754 | 0.9583 | 0.940 | 0.878 | 0.63 |
| XGBoost (rival) | 0.9744 | 0.9585 | 0.9596 | 0.898 | 0.46 |
| LightGBM (rival) | 0.9748 | 0.9574 | **0.9666** | **0.929** | 0.43 |

**Reading it honestly.** The shipped standardized LR is **best on test PR-AUC (0.9595)** and
**6–10× faster** (0.067 ms, stdlib-only inference, readable reason codes). On the harder
**adaptive-seller** distribution shift, LightGBM generalizes best (PR 0.929 vs LR 0.886) — tree
models absorb the shift better. LR was the right shipping choice under the **stdlib-only serve
constraint** (no sklearn at inference) + interpretability + latency, until §4.2 served LightGBM
trees in pure Python. The red-flag knowledge base and
never-auto-decline policy carry the protective behaviour, not raw ranking. **No public real
credit-boost/CPN dataset exists**, so these numbers show recovery of the generator's signal only.
The existing `TRAINING_REPORT.json` already measured LR vs HGB end-to-end with decision-level CIs;
this adds XGBoost/LightGBM rivals on the identical featurize+split.

**Caveat on the table above.** It refits a v1-style LR on the main train split and scores all
10,000 adaptive rows. The v2 artifact `credit_brain_v2.json` (the default until v3) trained on 50%
of the adaptive seller rings, so the table does not measure it on a clean holdout. §4.1 and §4.2 do.

### 4.1 v2 artifact vs ONNX Runtime serving (measured; v2 was the default until §4.2)

Harness: `ai-brain/training/bench_credit_onnx.py` → `ai-brain/benchmarks/credit_onnx/`.
- Reproduces the exact v2 splits and refuses to run if the row counts differ from the model file.
  Splits: train 28,067 / val 8,985 / test 8,028 / ring-grouped adaptive holdout 4,920.
- The shipped weights are rebuilt as a hand-written ONNX graph (opset 17).
- A 64×32 MLP is trained on the same train split and exported to ONNX as a deep-learning candidate.
- Thresholds for new models are picked on val with the trainer's rule. The decision rules apply
  the hard red flags as in `CreditBrain.assess`.
- Latency is measured single-row, featurize plus score, ONNX Runtime with 1 thread, Python 3.14,
  ORT 1.31.1 CPU.

| Model | test ROC | test PR | holdout ROC | holdout PR | holdout recall (any action) | holdout FPR (any action) | holdout recall (review) | p50 ms |
|---|---|---|---|---|---|---|---|---|
| **json_lr (shipped v2, stdlib)** | 0.9733 | 0.9576 | 0.9535 | 0.9189 | 0.896 | **0.0169** | 0.852 | **0.0073** |
| onnx_lr (same weights) | 0.9733 | 0.9576 | 0.9535 | 0.9189 | 0.896 | 0.0169 | 0.852 | 0.0102 |
| onnx_mlp_64x32 (DL candidate) | **0.9796** | **0.9601** | 0.9604 | 0.9310 | 0.930 | 0.0307 | 0.916 | 0.0110 |
| HGB (python) | 0.9774 | 0.9600 | **0.9630** | 0.9354 | **0.933** | 0.0547 | 0.916 | 0.295 |
| LightGBM (python) | 0.9760 | 0.9575 | 0.9596 | **0.9369** | 0.926 | **0.0151** | **0.926** | 0.204 |

**Parity.** ONNX and JSON outputs agree to max |Δp| 2.9e-7 on test and 3.3e-7 on holdout. Test
decisions agree 100%.

**Is ONNX an improvement?** Not for the shipped LR. Results are identical, and it is 1.4× slower
because a 34-feature dot product costs less than the ONNX Runtime call overhead.
- The MLP ranks better (holdout PR 0.931 vs 0.919, review recall 0.916 vs 0.852). Under the same
  val threshold rule, though, it nearly doubles holdout any-action FPR (0.031 vs 0.017). That is a
  trade-off, not a strict win.
- LightGBM is the only candidate that improves recall *and* FPR together. It needed a tree
  runtime (`onnxmltools` is not installed), so §4.2 serves the same kind of trees in pure Python
  instead. That model (v3) is now the default.

**Live check, no fallback (re-run 2026-11-15 on the v3 + hybrid-RAG build).** I started uvicorn
on 127.0.0.1 and called it over real HTTP with one keep-alive httpx client:
- `/health` reports:
  - `credit_model_loaded: true`, `credit_model_version: credit-brain-lgbm-v3`;
  - `rag_hybrid_loaded: true`, `rag_dense_backend: bge_small_onnx_int8`;
  - `knowledge_entries: 7`.
- Credit scoring returns real probabilities and no `from_fallback` field:
  - prime applicant: 0.0001 → `approve_standard_checks`;
  - seller-run CPN package: 0.9996 → `manual_review`, `auto_decline: false`.
- `/v1/triage`:
  - A UNION-SELECT SQL injection alone scores 0.7465 → `constrain`. Payload-only telemetry cannot
    go higher (§5.1).
  - The same payload with `behavior_anomaly 0.4` scores 0.8481 → `isolate_session`.
  - A benign banking question scores 0.2315 → `allow`.
- HTTP latency, 400 sequential requests, Python 3.14, 1 worker:
  - triage p50 3.93 / p95 12.24 / p99 13.61 ms, including the bge int8 query encoding;
  - credit p50 0.80 / p95 1.18 / p99 1.28 ms.
  - The earlier v2 figure (p50 9.2 / p95 20.1 ms) should not be compared with these directly; this
    run reuses one connection.
- `ai-brain/tests`: 27/27 pass with the encoder present. Without it, as in CI, 22 pass and 5 skip.

### 4.2 v3: LightGBM trees served in pure Python (measured, ADOPTED as the default)

Trainer and harness: `ai-brain/training/train_credit_brain_v3.py`. Outputs:
`ai-brain/models/credit_brain_v3.json` and `ai-brain/benchmarks/credit_v3/credit_v3_benchmark.{json,md}`.
**SYNTHETIC DATA ONLY.**
- **Splits:** exactly the v2 splits. The trainer verifies them against `credit_brain_v2.json` and
  refuses to run on a mismatch.
  - train 28,067 / val 8,985 / test 8,028 (651 pos) / ring-grouped adaptive holdout 4,920 (298 pos);
  - data sha256 `504af712…` (`credit_apps.csv`) and `65222ae3…` (`credit_apps_adaptive.csv`).
- **Model:** LightGBM 4.7.0, 300 trees, 31 leaves, lr 0.05, subsample and colsample 0.8,
  min_child_samples 50. Training takes 0.38 s on 16 threads.
- **Serving:** the booster dump is flattened to JSON arrays and traversed with stdlib Python
  (665,786 bytes). No lightgbm, sklearn or ORT is needed at serve time. Parity against
  `lightgbm.predict_proba` on test: max |Δp| 0.0.
- **Reason codes:** Saabas path attribution on the same trees; it sums exactly to the logit.
- **Thresholds:** chosen on val with the v2 rule (val FPR target 0.005, recall target 0.95):
  t_low 0.010413, t_high 0.014313. Hard red flags and never-auto-decline apply as in v2.
- **New stress sets:** an unseen generator seed (777001), 10,000 rows, 748 fraud.
  - `stress_fresh_rings`: unseen adaptive seller rings.
  - `stress_stealth_graft`: each fraud row copies 3–6 attacker-controllable fields from a random
    legit row (phone/email age, address match, device fan-out, document tamper score, inquiries).
    Bureau-side facts are left untouched because an applicant cannot rewrite them.

End-to-end decisions through `CreditBrain.assess`, hard flags included. Wilson 95% CIs are in the
JSON; a few are shown in brackets.

| Set | Model | PR-AUC | recall (any action) | FPR (any action) | recall (manual review) | FPR (manual review) |
|---|---|---|---|---|---|---|
| test | v2 LR | 0.9576 | 0.952 | 0.0199 | 0.952 | **0.0133** |
| test | **v3 LGBM** | 0.9575 | 0.952 | **0.0184** | 0.952 | 0.0159 |
| adaptive holdout | v2 LR | 0.9189 | 0.896 [0.856–0.926] | 0.0169 | 0.852 [0.808–0.888] | **0.0121** |
| adaptive holdout | **v3 LGBM** | **0.9369** | **0.926 [0.891–0.951]** | **0.0151** | **0.926 [0.891–0.951]** | 0.0123 |
| stress fresh rings | v2 LR | 0.9318 | 0.902 [0.879–0.922] | 0.0191 | 0.877 | **0.0120** |
| stress fresh rings | **v3 LGBM** | **0.9421** | **0.931 [0.910–0.947]** | **0.0165** | **0.929** | 0.0142 |
| stress stealth graft | v2 LR | 0.9262 | 0.894 | 0.0191 | 0.861 | **0.0120** |
| stress stealth graft | **v3 LGBM** | **0.9420** | **0.931** | **0.0165** | **0.929** | 0.0142 |

Latency (`assess`, single row, in-process):
- v2: p50 0.0107 / p95 0.0132 / p99 0.0164 ms.
- v3: p50 0.2047 / p95 0.259 / p99 0.3949 ms. That is 19× slower but still sub-millisecond.

**Reading it honestly.**
- **v3 improves recall and FPR together.** Any-action recall rises and any-action FPR falls on the
  adaptive holdout and both stress sets; test recall is unchanged. That meets the adoption rule.
  - `CreditBrain` now loads v3 by default (`credit-brain-lgbm-v3`).
  - v1/v2 still load for rollback via `CREDIT_BRAIN_MODEL_PATH`.
- **Trade-off:** manual-review FPR rises slightly (test 0.0159 vs 0.0133; stress 0.0142 vs
  0.0120), because more of v3's flags land in the review band. Fewer applications are handled
  wrongly overall, but a few more go to a human.
- **Stealth grafting:** it does not move v3 (recall 0.9305 on both stress sets). It costs v2 a little
  (0.902 → 0.894). The likely reason is that v3 leans on bureau-side facts an applicant cannot
  rewrite.
- The same generator wrote the train and stress data. This shows recovery of the generator's
  signal under shift, not real-world credit-fraud quality.

---

## 5. RAG retrieval: fraud-gate case memory (gap) and ai-brain triage (§5.1, deployed)

Retrieval tooling exists (`fraud-gate/training/evaluate_case_retrieval.py`, `build_retrieval_pairs.py`,
`build-check/v4-retrain/retrieval_pairs.jsonl`, 1,521 pairs). The **already-measured** neural baseline
(`build-check/v4-retrain/retrieval_neural_base.json`, Redis 7, bge-small-en-v1.5 bi-encoder +
ms-marco-MiniLM-L-6-v2 cross-encoder, 6,146-row corpus, 200 queries):

| Candidate strategy | recall@5 vs full-corpus top-10 | majority-vote acc@5 | p50 latency |
|---|---|---|---|
| full_corpus | 0.036 | 0.885 | 5,858 ms |
| legacy_page (first 128) | 0.040 | 0.830 | 7,161 ms |
| lsh_buckets (v4) | **0.120** | 0.875 | 9,184 ms |

**Honest caveats.** (1) This metric is **candidate-generation recall** (how well a bounded strategy
recovers the full-corpus top-10), **not** relevance recall against analyst-confirmed cases — verdicts
are L4 labels mapped to FRAUD/BENIGN. (2) **p50 latency is 5.9–9.2 seconds/query**, far above the
V5_DESIGN G4 goal of ≤100 ms. (3) The `full_corpus` scenario suffers the 128-candidate positional
truncation bug. **A true relevance recall@10 / MRR benchmark vs bge/gte/e5 rivals is NOT run here**:
it needs a live Redis + `sentence-transformers` (absent from system Python) + a labelled
query→relevant-case set. This is a real, open gap (G4), not a solved item. The hashed-vector default
matcher remains the fail-safe; neural is opt-in.

### 5.1 Triage RAG in ai-brain `/v1/triage`: hybrid retrieval (measured, DEPLOYED)

This is a separate component from the fraud-gate case memory above. Before this change,
`/v1/triage` "retrieved" with regex signatures only. It now takes the union of the regex hits and a
hybrid retriever (`ai-brain/rag_engine.py`). The hybrid is escalate-only.

**Architecture (all offline, no external calls).**
1. **Canonicalize the query:** NFKC, strip zero-width characters, and decode URL and HTML entities
   (up to 2 rounds). Then redact emails to `<email>` and Luhn-valid 13–19-digit runs to `<pan>`,
   and lowercase.
2. **Knowledge base:** 7 classes (T1190, T1059, T1566, T1110, T1071, CB-CPN, CB-TL) and 55
   documents. Each class contributes its name + mitigation, plus curated docs: T1190 10, T1059 10,
   T1566 10, T1110 5, T1071 5, CB-CPN 4, CB-TL 4.
3. **Sparse retrieval:** BM25 (k1 1.2, b 0.75) over word and symbol tokens. The tokenizer
   (`[a-z0-9_@]+|[^\sa-z0-9_@]{1,3}`) keeps `'`, `--`, `<`, `|` and `;` searchable.
4. **Dense retrieval:** BAAI/bge-small-en-v1.5 (MIT, ~33M params).
   - Exported by `training/export_bge_onnx.py` to ONNX opset 17 with dynamic int8, using eager
     attention.
   - CLS pooling, L2-normalised 384-d vectors, 256 tokens, onnxruntime CPU with 4 threads.
   - 33,972,472 bytes.
   - Cosine parity against torch fp32 on 577 eval texts: mean 0.99651, min 0.96455.
5. **Fusion:** reciprocal rank fusion of the BM25 and dense rankings (k = 60), top 10 documents.
6. **Reranker:** a logistic model (`models/rag_reranker.json`) over five per-class features:
   - dense_max;
   - log1p(BM25 max);
   - RRF × 60 (max within the top 10);
   - idf-weighted query coverage;
   - regex hit.
7. **Bands:** probability ≥ 0.93346 is a challenge-band hit; ≥ 0.96779 is a block-band hit.
8. **Union in `app.py`:**
   - A regex hit or a block-band hybrid hit uses the class weight.
   - A challenge-band hybrid hit uses min(weight, 0.5).
   - Hybrid hits only add threats; they never remove a regex hit.
   - If `models/bge_small/model_int8.onnx` is missing, the reranker (fitted for that encoder) is
     disabled and triage is regex-only. `/health` then shows `rag_hybrid_loaded: false`.

**Eval set.** Built by `ai-brain/training/build_rag_eval.py --authorized-data` into
`datasets/new_custom_datasets/out/rag_eval/`: 5,770 rows, 825 duplicates dropped, sha256
`11f8ee29…4d97e8c`. Gold labels are KB class ids.
- **T1190** (SQL injection) and **T1059** (command injection + XSS): PayloadsAllTheThings Intruder
  lists (MIT, pinned commit `08ea40e7`).
- **T1566** (prompt injection): the malicious rows of codesagar/malicious-llm-prompts-v3 (licence
  not stated).
  - It aggregates Lakera gandalf, jackhhao jailbreak, deepset/prompt-injections (Apache-2.0) and
    synthetic prompts.
  - The standalone deepset parquet is also read, but every row duplicates a codesagar row and is
    removed by dedupe.
- **Benign:** the same corpora's benign rows, plus the unique benign payloads of the CHIMERA layer
  CSVs.
- **Split:** stable hash of the normalized text, 40% dev / 60% test (seed 20261115).
  - Dev: 1,282 attack / 1,075 benign.
  - Test: 1,899 attack (T1059 395, T1190 429, T1566 1,075) / 1,514 benign.
- **No labelled text exists for T1110, T1071, CB-CPN or CB-TL.** They appear only as false-hit
  targets.

**Protocol.** Harness: `ai-brain/training/bench_rag.py` → `ai-brain/benchmarks/rag/rag_benchmark.json`.
- The reranker is fitted on even-indexed dev rows; thresholds are set on odd-indexed dev rows.
- **Headline cut:** the lowest t ≥ 0.5 with dev benign false-hit ≤ 0.02.
- **Deployed cut:** raised to match the regex's own dev false-hit rate (0.0112).
- Every number below is on test.

| Variant (headline cut) | Attack hit recall | Top-hit acc | Benign false-hit | Class MRR | Doc R@10 | Doc MRR | nDCG@10 | End-to-end p50 / p95 / max ms |
|---|---|---|---|---|---|---|---|---|
| regex (previous system) | 0.159 | 0.156 | **0.0086** | — | — | — | — | 0.041 / 0.609 / 25.8 |
| hybrid, hashed char n-grams, compact KB | 0.171 | 0.169 | 0.0218 | 0.620 | 1.000 | 0.575 | 0.678 | 0.50 / 4.12 / 36.2 |
| hybrid, hashed char n-grams | 0.416 | 0.416 | 0.0185 | 0.899 | 0.995 | 0.885 | 0.505 | 1.95 / 6.68 / 36.3 |
| hybrid, bge-small torch fp32 | 0.681 | 0.679 | 0.0185 | **0.948** | 0.996 | **0.931** | **0.647** | 11.2 / 46.9 / 446.4 |
| **hybrid, bge-small ONNX int8** | **0.687** | **0.683** | 0.0218 | 0.945 | **0.997** | 0.925 | 0.642 | **2.89 / 10.81 / 13.57** |

The regex latency is the bare `_retrieve` call. Hybrid latency is `HybridRetriever.retrieve` on
every 4th test row, including query encoding.

At the deployed (regex-matched) operating point:

| Variant | Attack hit recall | Benign false-hit |
|---|---|---|
| regex (previous system) | 0.159 | 0.0086 |
| hybrid hashed alone | 0.357 | 0.0099 |
| hybrid bge fp32 alone | 0.602 | 0.0086 |
| hybrid bge int8 alone | 0.603 | 0.0099 |
| union: regex + hybrid hashed | 0.360 | 0.0139 |
| **deployed union: regex + hybrid bge int8** | **0.6045** | 0.0159 |

Per-source attack hit rate, regex → deployed union (test):

| Source | n | regex | union |
|---|---|---|---|
| Lakera gandalf (via codesagar) | 523 | 0.094 | 0.816 |
| jackhhao jailbreak | 378 | 0.090 | 0.669 |
| deepset prompt-injections | 149 | 0.013 | 0.094 |
| PATT Generic_UnionSelect | 96 | 0.833 | 0.969 |
| PATT Generic_ErrorBased | 86 | 0.000 | 0.105 |
| PATT command_exec | 88 | 0.102 | 0.296 |
| PATT command-execution-unix | 47 | 0.000 | 0.085 |
| PATT RSNAKE XSS | 40 | 0.175 | 0.900 |
| PATT 0xcela event handlers | 65 | 0.000 | 0.000 |

**Decision level.** `ai-brain/training/bench_triage_decisions.py` calls `app.triage` exactly as
the API does, on the test split → `ai-brain/benchmarks/rag/triage_decisions.json`. "Escalated"
means step_up + constrain + isolate.

| Variant | Attack: allow | Attack: step_up | Attack: constrain | Attack escalated | Benign escalated |
|---|---|---|---|---|---|
| regex only (previous) | 0.829 | 0 | 0.171 | 0.171 | **0.0086** |
| **deployed union, challenge weight 0.5** | **0.373** | 0 | 0.627 | **0.627** | 0.0159 |
| what-if: challenge weight 0.45 | 0.373 | 0.238 | 0.389 | 0.627 | 0.0159 (step_up 0.004, constrain 0.012) |

No variant reaches `isolate_session` on payload-only telemetry. Risk is
logistic(2.4·w − 1.2), which is at most 0.7465 for the strongest class weight (0.95). Isolation needs
behavioural anomaly or an invalid workload identity.

**Reading it honestly.**
- **Upgraded, and it helps.** At the regex's own false-hit budget, the hybrid alone finds 3.8× the
  attacks (0.603 vs 0.159).
  - Deployed as a union, attack escalation rises from 0.171 to 0.627 (3.7×).
  - Benign escalation rises from 0.0086 to 0.0159, i.e. 11 more of 1,514 benign queries.
- **int8 costs nothing in quality.** The int8 encoder matches torch fp32 (0.687 vs 0.681 recall at
  the headline cut). It is ~4× faster end-to-end (p50 2.9 vs 11.2 ms; max 13.6 vs 446 ms).
- **What drives the gain:**
  - The dense encoder: hashed char n-grams reach 0.416, bge reaches 0.687.
  - The curated KB docs: the compact KB (name + mitigation only) collapses to 0.171.
- **Weak spots (test):** short SQL fragments and shell one-liners still slip through, e.g.
  `1 AND SLEEP(5)`, `<body onload=...>`, `| cat /etc/passwd`, `&& whoami`.
  - Union hit rates: Generic_ErrorBased 0.105, command-execution-unix 0.085, 0xcela event handlers
    0.0.
  - Benign false-hits concentrate in jackhhao benign rows (0.021) and a 20-row synthetic benign set
    (0.10).
  - 2 of 4 CHIMERA layer-2 benign payloads are hit by every variant, including the regex.
- **Policy option, not applied:** challenge-band hits land in `constrain` (risk exactly 0.5 at weight
  0.5), which means human review.
  - Lowering `CHALLENGE_WEIGHT` to 0.45 sends 24% of attacks to `step_up` instead, which has no
    human review.
  - The escalation rate is unchanged either way.
  - Kept at 0.5 pending a product decision.
- **Unmeasured:** recall for the 4 classes without labelled text (T1110, T1071, CB-CPN, CB-TL).
- **CI runs without the hybrid.** The encoder is a gitignored model artifact (34 MB), so CI triage
  is regex-only: 22 tests pass and 5 encoder tests skip. Re-create the encoder with
  `training/export_bge_onnx.py`.
- **No instruction stripping.** No LLM consumes the retrieved text today, so there is no
  instruction-stripping stage. Adding an LLM consumer would require one.

---

## 6. k6 and k8s — infrastructure, NOT trainable models

**2026-11-16 local verification supersedes the pending CAPTURE statement below.** Real monitoring now has 10/10 targets UP, 71 dashboard/rule expressions passing strict live checks, 17 healthy rule evaluations and four promtool fixtures. The service suite passed 71 tests (one image-only helper skip, separately passed locally); local data/contract tests passed 10/10. First 3-VU/60-second settlement run: 139/142 captured, three fail-closed `GATE_TIMEOUT` challenges, all 139 receipts valid, P95 379.18ms; capture-failure threshold failed. The identical run after model jobs finished: **160/160 captured with valid receipts**, zero HTTP failures, P95 **129.88ms**; all thresholds passed. Neither run proves production capacity, and the initial failure remains recorded. See [BENCHMARK.md](BENCHMARK.md) and [observability/README.md](observability/README.md).

Kubernetes gRPC/worker metrics Services and a safe local rendering/Kind harness are integrated. **20 resources passed structural checks; kind is absent**, so no cluster, API, Kubernetes load, ingress/HPA or Kubernetes monitoring-stack verification is claimed. Local Kind can load images without a registry when installed; shared-cluster deployment still needs an appropriate image distribution method. Grafana provisioning completed but browser rendering remains **NOT_VERIFIED** because the connector is disconnected. Alertmanager notification delivery is not configured.

**Category clarification:** `k6` is a load-testing tool and `k8s` is deployment orchestration. There
is no "model" to benchmark against a market rival. They are assessed as engineering artefacts:

- **k6** (`loadtest/k6/{checkout-load,cache-hit,idempotency-duplicate,saturation}.js`): load behaviour
  is **already measured** in `BENCHMARK.md` (read 48.11 / write 14.63 req/s, server P95 417.67 /
  P99 709.23 ms, 100/100 idempotent duplicates, 99.62% cache hit, recovery 42.5 s, index speedups
  71.76×/184.10×/1.60×). The 2026-11-14 follow-up changes (session lookup, BFF, audit `REQUIRES_NEW`)
  are **not yet re-load-benchmarked**. The 300 ms gate budget and 8–12 ms L4 target remain *targets*.
- **k8s** (`deploy/k8s/*.yaml`, 12 manifests): explicitly **"SANDBOX ONLY. UNTESTED."** Production-
  readiness gaps observed: ingress **TLS commented out** + placeholder host `chimera-checkout.local`;
  images are **local build tags** (`chimera-*:local`, TODO push to registry); HPA CPU target 70% is a
  **demo value, not measured** (needs metrics-server); no `securityContext` (runAsNonRoot /
  readOnlyRootFilesystem / drop caps), no PodDisruptionBudget, no NetworkPolicy, no anti-affinity.
  Probes correctly gate readiness on PostgreSQL/Redis health; resource requests/limits and a JVM
  startupProbe are present. These are scaffolds to harden before any real cluster, not benchmarked
  models.

---

## 7. Pre-benchmark code hardening performed

- **Card benchmark harness** (`bench_card_fraud.py`): fixed a LightGBM saturation bug (extreme
  `scale_pos_weight≈578` × 300 trees collapsed probabilities to 26 unique values, making the FPR
  budget infeasible) → regularized config (`min_child_samples=100, reg_lambda=5.0, n_estimators=200,
  subsample_freq=1`), which also gave the best validation PR-AUC. Added per-model failure isolation
  and an honest `fpr_budget_met` fallback instead of crashing.
- **L4 fine-tune** (`train_l4_v5_manual.py`): the HF `Trainer` path is blocked on this host
  (`Trainer → datasets → pyarrow._dataset` DLL blocked by Windows Application Control). Added a
  **Trainer-free manual PyTorch loop** that exports the exact runtime artefact (WordPiece `vocab.txt`,
  raw `[batch,2]` logits, opset 17, dynamic-int8, <100M params). The existing
  `train_l4_semantic_guard.py` is left intact for environments where Trainer works.
- **Two-slice calibration** (`calibrate_l4_v5.py`) and **family-level split hygiene**
  (`augment_l4_persona.py`) reused/available; the L4 benchmark selects ONE worst-case-FPR threshold
  across in-domain + external calibration, never on test.
- **Wire trainer** (`train_paysim_wire.py`) fills the "no PaySim trainer" gap with the strict
  `CardModel.load` contract + shared `engineer_features` (train==inference).
- **Contract verification:** the real card artefact loads via `CardModel.load` and scores correctly;
  credit `featurize`/`score` reviewed (shared train/serve, logit clamp, scale>0 guard); fail-closed
  paths confirmed (card `ModelUnavailable`, credit `manual_review`, L4 fail-closed CHALLENGE).

**Added 2026-11-15**

- **Triage RAG input handling** (`ai-brain/rag_engine.py`):
  - Queries are canonicalized (NFKC, zero-width removal, ≤ 2 rounds of URL and HTML decoding), so
    `%27%20OR%201%3D1` and `&lt;script&gt;` are matched as `' or 1=1` and `<script>`.
  - Emails and Luhn-valid 13–19-digit card numbers are redacted to `<email>` / `<pan>` before BM25
    or the encoder see them.
  - Tests: `test_canonical_decodes_and_redacts`, `test_missing_dense_encoder_disables_hybrid`.
- **Encoder export** (`training/export_bge_onnx.py`): the model is loaded with
  `attn_implementation="eager"`, because the export failed on the default SDPA attention path here.
- **Hybrid fail-safe:** the reranker is fitted on dense features. If the encoder file is missing,
  the hybrid is disabled and triage is regex-only, visible as `rag_hybrid_loaded: false`. It never
  falls back to a different encoder silently.
- **ai-brain packaging:**
  - `requirements.txt` now pins numpy, onnxruntime, tokenizers, httpx and pytest, so the
    `ai-brain.yml` CI job can import and test the engine. Every pin has a Python 3.12 Linux wheel
    (checked on PyPI).
  - The `Dockerfile` now copies `credit_brain.py`, `rag_engine.py` and `models/`. It used to copy
    only `app.py`, so the new imports would have failed at container start.
- **Deception vault persistence** (platform-api, completing the work in progress that broke the
  build):
  - `JpaVaultPersistence` writes every vault state transition to `deception_vault_entries`, with the
    snapshot sealed as AES-256-GCM (random 96-bit IV, 128-bit tag).
  - The key comes from `AuditCrypto` via HKDF-SHA256 with info `chimera/deception-vault/aes-256-gcm/v1`,
    so `hmac()` outputs never reveal it.
  - A failed durable write is logged and the entry stays in memory. It never undoes the quarantine;
    an exception would otherwise turn into a CHALLENGE and weaken the L6 verdict.
  - Tests: `AuditCryptoTest`, `JpaVaultPersistenceTest`.
  - Caveat: without `AUDIT_HMAC_KEY` the key is ephemeral, so stored rows cannot be decrypted after
    a restart.
- **Flyway:** two migrations were both numbered V2, which makes Flyway refuse to start. The newer one
  is now `V3__persistent_auth_sessions.sql`.
  - Verified on PostgreSQL 15 via Testcontainers: 3 migrations validated, V1→V3 applied, IT 4/4.
  - A stale `target/classes` copy of the old V2 file also breaks Flyway. Run `mvn clean` once after
    pulling; the copy in this workspace was removed.
- **Root `Dockerfile`:**
  - It now copies `contracts/`, which the gRPC stub generation needs.
  - It builds with `-Dmaven.test.skip=true`, so the image build does not compile the 7
    work-in-progress test files that currently fail to compile (§9).
- **Testcontainers 1.19.8 vs Docker Engine 29:** Docker 29 needs API ≥ 1.44, so Testcontainers
  reports Docker as unavailable.
  - `@Testcontainers(disabledWithoutDocker = true)` then skips all 4 integration tests silently,
    and the build is still green.
  - Passing `-Dapi.version=1.44` to the test JVM (argLine) fixes it: 4/4 run and pass. The
    `DOCKER_API_VERSION` env var alone does not (4 skipped).
  - CI was not changed. Recommended: upgrade Testcontainers, or add the property to the CI test
    command.
- **fraud-gate test env:** `build-check/fraud-gate-venv` points at another user's Python 3.13 and
  does not start. The 60 fraud-gate tests were run from a scratch venv `build-check/fg-test-venv`
  (system Python 3.14 + prometheus_client, redis, grpcio, grpcio-tools, skl2onnx): 60 passed.

---

## 8. Reproduce

```bash
# Card (real ULB) — HGB vs XGBoost vs LightGBM, temporal split
python fraud-gate/training/bench_card_fraud.py \
  --data datasets/new_custom_datasets/raw/creditcard_ulb/creditcard.csv \
  --out-dir fraud-gate/training/benchmarks/card --max-fpr 0.01 \
  --emit-artifact fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib

# Wire (PaySim) — HGB vs XGBoost vs LightGBM, temporal split by step
python fraud-gate/training/bench_wire_fraud.py \
  --data datasets/new_custom_datasets/raw/paysim/paysim.csv \
  --out-dir fraud-gate/training/benchmarks/wire --max-fpr 0.01 \
  --emit-artifact fraud-gate/training/benchmarks/wire/paysim_wire_hgb.joblib

# L4 v5 fine-tune (Trainer-free) then benchmark vs rivals on locked slices
python fraud-gate/training/train_l4_v5_manual.py \
  --data datasets/new_custom_datasets/out/v5/l4_v5_train.jsonl \
  --base-model build-check/l4_base --output fraud-gate/training/artifacts/l4_semantic_guard_v5 \
  --version l4-semantic-v5 --epochs 2 --max-length 128 --authorized-data
python fraud-gate/training/bench_l4_guard.py \
  --v5-dir fraud-gate/training/artifacts/l4_semantic_guard_v5 \
  --v4-dir fraud-gate/training/artifacts/l4_semantic_guard_v4 \
  --v1-dir defense-pipeline/src/main/resources/models/l4_semantic_guard \
  --protectai-dir fraud-gate/training/benchmarks/rivals/protectai_deberta_v3 \
  --train-data datasets/new_custom_datasets/out/v5/l4_v5_train.jsonl \
  --in-domain-calib datasets/new_custom_datasets/out/v5/l4_v5_calib.jsonl \
  --external-calib datasets/new_custom_datasets/out/v5/l4_v5_external_calib.jsonl \
  --in-domain-test datasets/new_custom_datasets/out/v5/l4_v5_test.jsonl \
  --external-test datasets/new_custom_datasets/out/v5/l4_v5_external_test.jsonl \
  --max-fpr 0.02 --max-length 128 --out-dir fraud-gate/training/benchmarks/l4

# L4 v6 distillation on the RX 9070 XT (ROCm venv), then benchmark on CPU (system Python)
export TORCH_BLAS_PREFER_HIPBLASLT=0
build-check/rocm-venv/Scripts/python.exe build-check/l4_claude/distill_l4.py score --authorized-data \
  --text-field payload --device cuda ...   # teacher_scores_{train,extra}.jsonl -> teacher_scores_all.jsonl
SPECS=minilm_l12:8e-5 EPOCHS=12 sh build-check/l4_distill/run_students_v2.sh
python fraud-gate/training/bench_l4_guard.py --scorers tfidf \
  --student "chimera_l4_v6_minilm_distill (mine, new)=build-check/l4_distill/out_minilm_l12_v2" \
  --train-data datasets/new_custom_datasets/out/v5/l4_v5_train.jsonl \
  --in-domain-calib datasets/new_custom_datasets/out/v5/l4_v5_calib.jsonl \
  --external-calib datasets/new_custom_datasets/out/v5/l4_v5_external_calib.jsonl \
  --in-domain-test datasets/new_custom_datasets/out/v5/l4_v5_test.jsonl \
  --external-test datasets/new_custom_datasets/out/v5/l4_v5_external_test.jsonl \
  --max-fpr 0.02 --max-length 128 --out-dir build-check/l4_distill/bench_v6

# Credit brain (synthetic) — LR vs HGB/XGBoost/LightGBM
python ai-brain/training/bench_credit_brain.py \
  --data datasets/synthetic_credit_boost --out-dir ai-brain/training/benchmarks/credit
# Credit brain: shipped v2 JSON vs ONNX LR vs ONNX MLP on the reproduced v2 splits
python ai-brain/training/bench_credit_onnx.py --out-dir ai-brain/benchmarks/credit_onnx

# Credit brain v3 (§4.2): LightGBM -> stdlib trees, v2 vs v3 on test / holdout / stress sets
python ai-brain/training/train_credit_brain_v3.py   # -> ai-brain/models/credit_brain_v3.json + benchmarks/credit_v3/

# L4 v7 / v7b (§3.4): research datasets + persona generator, teacher-scored, distilled on the GPU
V=datasets/new_custom_datasets/out/v5
python fraud-gate/training/build_l4_v7_corpus.py    # -> datasets/new_custom_datasets/out/v7/l4_v7_extra.jsonl + MANIFEST_V7.json
build-check/rocm-venv/Scripts/python.exe build-check/l4_claude/distill_l4.py score --authorized-data \
  --text-field payload --device cuda --teacher fraud-gate/training/benchmarks/rivals/protectai_deberta_v3 \
  --data datasets/new_custom_datasets/out/v7/l4_v7_extra.jsonl --out build-check/l4_v7/teacher_scores_v7.jsonl \
  --forbid-overlap-with $V/l4_v5_calib.jsonl --forbid-overlap-with $V/l4_v5_test.jsonl \
  --forbid-overlap-with $V/l4_v5_external_calib.jsonl --forbid-overlap-with $V/l4_v5_external_test.jsonl
cat build-check/l4_distill/teacher_scores_all.jsonl build-check/l4_v7/teacher_scores_v7.jsonl \
  > build-check/l4_v7/teacher_scores_v7_all.jsonl                     # 22,874 + 16,893 = 39,767 rows
sh build-check/l4_v7/run_v7.sh                                        # v7
python -c "import json; src=open('build-check/l4_v7/teacher_scores_v7_all.jsonl',encoding='utf-8',newline='').read().split('\n'); \
open('build-check/l4_v7/teacher_scores_v7b_all.jsonl','w',encoding='utf-8',newline='').write(''.join(l+'\n' for l in src \
if l.strip() and not json.loads(l)['source'].startswith(('bipia/','llmail/'))))"   # v7b: 33,130 rows
DATA=build-check/l4_v7/teacher_scores_v7b_all.jsonl TAG=v7b sh build-check/l4_v7/run_v7.sh
python build-check/l4_gemini/compare_students.py --student v6=build-check/l4_distill/out_minilm_l12_v2 \
  --student v7=build-check/l4_v7/out_v7 --student gemini_B=build-check/l4_gemini/out_B \
  --ensemble v6+gemini_B --ensemble v7+gemini_B --ensemble v6+v7 --out build-check/l4_v7/compare.json   # §3.3/§3.4

# Triage hybrid RAG (§5.1): eval set -> int8 encoder -> fit + benchmark -> decisions -> deploy reranker
python ai-brain/training/build_rag_eval.py --authorized-data        # -> datasets/new_custom_datasets/out/rag_eval/
python ai-brain/training/export_bge_onnx.py                         # build-check/students/bge_small -> ai-brain/models/bge_small
python ai-brain/training/bench_rag.py --bge-onnx ai-brain/models/bge_small --bge build-check/students/bge_small
python ai-brain/training/bench_triage_decisions.py --what-if-challenge-weight 0.45
cp ai-brain/benchmarks/rag/rag_reranker_hybrid_bge_small_onnx_int8.json ai-brain/models/rag_reranker.json
```

---

## 9. What is NOT claimed

- No real-world fraud-detection quality for synthetic data (credit brain, PaySim).
- No production deployment, real PayPal, real cards/accounts, or hosted/browser verification.
- Rival published numbers are **cited, not reproduced**; ProtectAI DeBERTa-v3 detects **prompt
  injection, not jailbreaks**, and is 184M params (**> the 100M L4 runtime cap** — a quality
  reference, not deployable in L4). `meta-llama/Prompt-Guard-86M` is **gated** (HF token required);
  its published ~0.98 recall is cited, not reproduced here.
- L4 in-domain scores carry **origin-style leakage** (ultrachat 0% malicious, gandalf 100% malicious);
  the **external SPML test** is the honest generalization slice.
- The CAPTURE saga is **not yet load-benchmarked** with the trained card gate, and the trained
  artifact is **not promoted** into `fraud-gate/artifacts/` (§1); k8s is untested scaffold.
- **Fraud-gate case-memory** relevance benchmark (G4): still **not run**, because there is no
  labelled query→relevant-case set.
- **Triage RAG:** the relevance benchmark is run (§5.1), but recall for T1110, T1071, CB-CPN and
  CB-TL is **unmeasured** (no labelled text). The CI build has no encoder, so CI exercises the
  regex-only path.
- **Credit v3** was adopted on **synthetic** data only (§4.2); its margin over v2 is a synthetic
  result.
- **L4 v7 / v7b and all ensembles** were measured and **not adopted** (§3.3–§3.4).
  - The bundled L4 model is still the v1 toy.
  - The semantic guard is opt-in via `L4_SEMANTIC_MODEL_PATH`.
- **Platform-api WIP tests:** 7 untracked work-in-progress test files do not compile against the
  current main code (31 errors).
  - The quoted platform-api count (66/66) excludes them.
  - They need a decision: update them to the current APIs, or remove them.

### 9.1 Genuine datasets still missing (to be sourced by the owner)

| Need | Where | Why it is not here | What it unblocks |
|---|---|---|---|
| Llama Prompt Guard 2 (model) | HF, gated | needs an accepted licence + HF token | reproduce the strongest small L4 rival instead of citing it |
| HackAPrompt (full), WildJailbreak | HF, gated | accept terms + HF token | larger, more diverse L4 jailbreak training and test data |
| Tensor Trust | research release | no licence stated, so it was excluded | L4 attacker-written injections |
| BIPIA (official release) | github.com/microsoft/BIPIA | v7 used an HF mirror | confirms the provenance of the §3.4 BIPIA rows |
| BAF (Feedzai, NeurIPS 2022) | Kaggle `sgpjesus/bank-account-fraud-dataset-neurips-2022` | no Kaggle credentials here | an account-opening fraud gate; the nearest public stand-in for the credit brain (itself generated, not raw real data) |
| IBM AMLworld | Kaggle | no Kaggle credentials here | wire / AML laundering patterns (PaySim is the only wire set) |
| Real credit-boost / CPN applications | partner bank, under a data agreement | not public by nature | any real-world claim for the credit brain |
| Labelled text for T1110, T1071, CB-CPN, CB-TL | none found | no public labelled corpus | triage RAG recall for 4 of its 7 classes |
| L5 bot vs human interaction recordings | none found | no public set matching L5's signals | trained L5 instead of rules |
| L6 deception-vault logs | internal | no production traffic yet | L6 tuning |
| PayloadsAllTheThings `IntrudersXSS.txt` | PATT repo | quarantined by the local antivirus on download | more XSS rows in the RAG eval |
| codesagar/malicious-llm-prompts-v3 licence | HF page | licence not stated | redistribution of anything built from it (the L4 v5 slices and the RAG eval) |

Present but not yet run:
- **IEEE-CIS**, user-supplied in `datasets/new_datasets_v2/`, is ready for the card gate.
- **HF `YangYang-Research/web-attack-detection`** (MIT, 625,904 SQLi/XSS/command-injection/LFI rows;
  not fetched yet) targets the §5.1 weak spots: short SQL fragments and shell one-liners.

## 10. Sources (rival / SOTA context, web)

- ULB dataset: https://www.kaggle.com/mlg-ulb/creditcardfraud/data
- GA-XGBoost ULB (PR-AUC 0.798 / ROC 0.967): https://www.mdpi.com/2076-3417/16/13/6734
- Stacked ensembles ULB (AUC-PR 0.821): https://papers.ssrn.com/sol3/Delivery.cfm/7266518.pdf?abstractid=7266518&mirid=1
- ProtectAI DeBERTa-v3 prompt-injection-v2: https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2
- Prompt-injection detector comparison (Prompt-Guard numbers): https://www.armosec.io/blog/prompt-injection-detection-models/
- Firewall comparison (DeBERTa vs Llama-Guard): https://neuraltrust.ai/blog/prevent-prompt-injection-attacks-firewall-comparison
- Comparative ML eval for prompt injection: https://link.springer.com/article/10.1007/s10207-026-01264-8
- MTEB / embedding choice (bge/gte/e5): https://huggingface.co/BAAI/bge-small-en-v1.5
- BIPIA, indirect prompt injection benchmark (§3.4): https://arxiv.org/abs/2312.14197 ·
  official code/data: https://github.com/microsoft/BIPIA
- LLMail-Inject, adaptive prompt-injection challenge data (§3.4): https://arxiv.org/abs/2506.09956
- SPML, the external L4 test slice: https://arxiv.org/abs/2402.11755
- Tensor Trust (excluded: no licence): https://arxiv.org/abs/2311.01011
- HackAPrompt (gated): https://arxiv.org/abs/2311.16119
- neuralchemy prompt-injection dataset (§3.4): https://huggingface.co/datasets/neuralchemy/Prompt-injection-dataset
- PayloadsAllTheThings, the SQLi/XSS/command-injection rows of the §5.1 eval: https://github.com/swisskyrepo/PayloadsAllTheThings
- deepset prompt-injections (Apache-2.0): https://huggingface.co/datasets/deepset/prompt-injections
- codesagar malicious-llm-prompts-v3 (licence not stated): https://huggingface.co/datasets/codesagar/malicious-llm-prompts-v3
- Reciprocal rank fusion (§5.1): Cormack, Clarke & Büttcher, SIGIR 2009.
- Not yet used (§9.1): BAF https://www.kaggle.com/datasets/sgpjesus/bank-account-fraud-dataset-neurips-2022 ·
  web-attack-detection https://huggingface.co/datasets/YangYang-Research/web-attack-detection