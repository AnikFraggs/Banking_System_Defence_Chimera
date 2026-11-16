# CHIMERA Checkout Shield — v5 Problem Statement

**Audience:** a frontier model asked to design the v5 solution. This document is self-contained:
architecture with exact file references, every measured result that defines "bad", the root-cause
evidence, the hard runtime constraints, and the open questions. Companion documents:
`RESULTS_DOSSIER.md` (full per-layer inventory + all numbers), `V5_DESIGN.md` (the current team's
v5 proposal — critique it), `fraud-gate/training/README_V4.md`, `datasets/new_custom_datasets/EVALUATION.md`.

**Honesty contract:** every number below was measured on this host and traces to a file (§10).
Nothing is a target dressed as a result. Where a number is a design goal it is labelled **goal**.
PayPal is stub-only; no real cards/accounts; no production-readiness claim.

> **UPDATE 2026-11-14:** the card gate (P6) is now trained on the real local ULB CSV and the wire gate
> has a trainer + measured PaySim artefact; L4 v5 is fine-tuned. Measured rival benchmarks, provenance
> and goal status are in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md). **G1 (SPML-native recall ≥50%
> @ FPR≤2%) is NOT met** by v5 (~16% external recall); the "card gate untrained / no wire trainer"
> statements below are stale.
>
> **UPDATE 2026-11-15:** G1 is still **not met** by any deployable model. The best candidate, v6 (a
> distilled 33M MiniLM), reaches SPML-native recall 0.409 vs 0.827 for the 184M ProtectAI rival.
> v7/v7b and the ensembles did not beat it (MODEL_BENCHMARKS §3.3–§3.4). The ULB card artifact is
> trained but **not promoted**: `fraud-gate/artifacts/` still holds a synthetic toy, so every card
> score fails closed (MODEL_BENCHMARKS §1).

**Date:** 2026-11-14. **Status of v4:** trained, measured, deployed in compose. **Status of v5:**
data downloaded (§8), scripts being wired, **no v5 training has been run**. A 256-token candidate
retrain was started and **stopped after 8 of 782 CPU steps**; `build-check/l4_candidate_recall/`
contains only an empty `checkpoints/` dir — **no artifact, no quality claim** for it.

---

## 1. The headline problem

The L4 prompt-injection semantic guard (the only trained deep model in the system) looks strong
in-domain and collapses on truly unseen attacks:

| Operating point | In-domain test recall / FPR | SPML-native (unseen) recall / FPR |
|---|---|---|
| v4 @ deployed threshold 0.65 | 91.1% / 0.60% (end-to-end) | **16.7% / 9.9%** |
| v4 @ in-domain-calibrated 0.9642 (≤0.5% dev FPR) | 88.4% / 0.30% | **10.6% / 6.8%** |

The calibration that buys 0.30% FPR in-domain **does not transfer**: external FPR is 6.8–9.9%.
Raising recall on unseen persona-style jailbreaks without blowing the false-positive budget is the
core v5 problem. Secondary problems: a 128-token input window that provably hides 54.3% of missed
attacks, an invalid retrieval benchmark, an untrained card-fraud gate, and missing wire/BAF trainers.

### 1.1 Reconciliation with the numbers quoted in the task

- "90.3% recall / 0.3% FPR in-domain" = **semantic-only** v4 @0.65 (model without the deterministic
  rules; `build-check/v4-evals/probs_v4_test.json`, dossier §2.2). The **end-to-end** numbers are
  91.1%/0.60% @0.65 and 88.4%/0.30% @calibrated (rules + guard; dossier §2.1). Both are real; they
  measure different pipelines.
- "16.7% recall / 10.2% FPR on SPML-native": recall 16.7% matches exactly (1,397/8,373). The
  measured native FPR is **9.9% (335/3,372)**, Wilson 95% CI ≈ 8.9–11.0 — 10.2% falls inside that
  interval but no artifact produces exactly 10.2%; this document uses the measured 9.9%.
- "production threshold unchanged": correct — deployed threshold is still 0.65
  (`OnnxSemanticInjectionGuard.java:48`, compose `L4_SEMANTIC_THRESHOLD`); the calibrated 0.9642
  exists only in eval metadata, never deployed.

---

## 2. Hard constraints any v5 solution must respect

These are enforced in code, not preferences:

| Constraint | Where enforced |
|---|---|
| Encoder **< 100M parameters** | `fraud-gate/training/train_l4_semantic_guard.py` (`parameter_count >= 100_000_000` → SystemExit) |
| Java runtime requires **WordPiece `vocab.txt`** (BERT-style); current vocab is English-uncased 30,522 | `train_l4_semantic_guard.py` (tokenizer.vocab check); `defense-pipeline/.../detect/WordPieceTokenizer.java` |
| ONNX export opset 17, inputs `input_ids/attention_mask/token_type_ids` [batch,seq], output `logits` [batch,2]; dynamic batch+seq; dynamic-int8 quantization | `train_l4_semantic_guard.py` (OnnxWrapper + torch.onnx.export + quantize_dynamic) |
| Production inference timeout **250 ms** (config `chimera.defense.l4.semantic.timeout-ms`, legal range 1–1000 ms); timeout/error → **fail-closed CHALLENGE** | `OnnxSemanticInjectionGuard.java:47,72-73,127-132` |
| Guard is **escalate-only**: may lift PASS→CHALLENGE or CHALLENGE→BLOCK, never downgrade a deterministic hit | `defense-pipeline/.../layers/L4_InjectionLeakLayer.java` |
| Deterministic-first short-circuit: canary → QUARANTINE 0.98 without ONNX; rules-hit ≥0.7 → BLOCK without ONNX | `L4_InjectionLeakLayer.java` |
| Guard disabled → PASS fail-open (rules still run); configured-but-missing artifact → fail-closed | `OnnxSemanticInjectionGuard.java`, compose mounts |
| CPU-only training/inference host: i5-1334U 10C/12T, 15.7 GB, no GPU. torch 2.15.0+cpu | environment (§9) |
| LLM influence on fraud score capped **±0.05, asynchronous, informational only** | `fraud-gate/app/debate.py`, `worker.py` |
| Verdict cache: LRU SHA-256(exact text), errors/timeouts never cached | `detect/SemanticVerdictCache.java` |
| Scope: stub PayPal only; synthetic data must not contain SSN/CPN-like strings; "temporal graph features" (no trained GNN); Redis not Elasticsearch | project guardrails |

Trainer flags the user already added (available for v5, `train_l4_semantic_guard.py`):
`--max-length` 32..256 (default 128), `--positive-weight` 0.25..10 (weighted cross-entropy via
`RecallWeightedTrainer`), `--calibration-data` + `--max-calibration-fpr` (records
`threshold_is_operating_point_only: true` in metadata; threshold chosen by
`score_l4_onnx.py::choose_threshold`). The 256-token path is therefore *plumbed but untested*.

---

## 3. Architecture (with file references)

All paths relative to repo root `Banking_System_Defence_Chimera/`.

### 3.1 Request path (checkout)

```
web (React) → platform-api (Spring Boot 3.3.5, JDK 21)
  ├─ in-process DefensePipeline: L1 IP → L2 role → L3 purpose → L4 injection/leak → L5 human → L6 vault
  │    defense-pipeline/src/main/java/com/chimera/bank/defense/
  │      DefensePipeline.java, DefenseOrchestrator.java
  │      layers/L1_IpReputationLayer.java … L6_DeceptionVaultLayer.java
  │      L4 = layers/L4_InjectionLeakLayer.java
  │           ├─ detect/InjectionScanner.java        (Unicode/bidi/homoglyph/nested-encoding/phrasing rules)
  │           ├─ detect/CanaryTokenRegistry.java     (canary → QUARANTINE 0.98)
  │           ├─ detect/ConfusableNormalizer.java, NestedEncodingDecoder.java
  │           └─ detect/OnnxSemanticInjectionGuard.java (int8 ONNX, WordPieceTokenizer.java,
  │                SemanticVerdictCache.java; interface SemanticInjectionGuard.java)
  ├─ FraudGateClient.java → fraud-gate (FastAPI + gRPC, Python 3.13)
  │    fraud-gate/app/main.py, grpc_server.py, decision_service.py, scoring.py, policy.py
  │      card_model.py / onnx_card_model.py  ← UNTRAINED (artifacts/ empty) → fail-closed CHALLENGE
  │      temporal_graph.py, rolling_counters.py (rule-based "temporal graph features", Redis)
  │      biometrics.py, evidence.py, image_forensics.py (rules)
  │    async worker.py → debate.py (deterministic stub, ±0.05 informational)
  │                    → case_memory.py (Redis RAG) → case_matching.py (hashed default / neural opt-in)
  └─ AiBrainClient.java → ai-brain (FastAPI)
       ai-brain/app.py (/v1/triage: regex KB + hand-weighted logistic, NOT trained;
                        /v1/credit: credit_brain.py + models/credit_brain_v2.json, synthetic-trained LR)
```

Fail-safe semantics: any layer exception → CHALLENGE (`DefensePipeline.java`); fraud-gate
timeout/breaker-open → CHALLENGE score 0.5 (`ResilientFraudGateConfig.java`); ai-brain offline →
local severity (`AiBrainSeverityAdvisor.java`, `SeverityAdvisor.LOCAL_ONLY`).

### 3.2 Training / eval path (offline)

```
datasets/new_custom_datasets/
  raw/…                          (codesagar_v3, spml, + v5 downloads §8; MANIFEST.json per source)
  chimera_datasets (build/score) → out/text_{train,dev,test}.csv, out/v4/… (leakage-safe hash splits, seed 13)
fraud-gate/training/
  prepare_l4_v4_data.py          (v4 recipe: truncate>2000, weak-source repeat, dev hard-neg mining,
                                  reserved calibration half; leakage assertions)
  train_l4_semantic_guard.py     (fine-tune bert-mini base build-check/l4_base → ONNX int8 + vocab.txt)
  score_l4_onnx.py               (OnnxScorer, choose_threshold, confusion, Wilson CIs)
  retrain_v4.py                  (orchestrator: l4-data/l4-train/l4-eval/retrieval/credit/card/wire steps)
  build_retrieval_pairs.py, train_contrastive.py, evaluate_case_retrieval.py
  train_creditcard_hgb.py, evaluate_creditcard_hgb.py   (card; needs raw/creditcard_ulb/creditcard.csv)
  train_creditcard_hgb_synthetic.py, hard_negative_synthesis.py, train_lora_verdicts.py,
  train_safe_lcb.py              (tooling; LoRA/Safe-LCB never run, no artifacts)
defense-pipeline/src/test/java/…/L4RealDataEvaluation.java  (Java end-to-end harness, -Dchimera.eval.*)
defense-pipeline/src/test/java/…/AdversarialValidationTest.java (200+ synthetic battery gate:
                                  recall ≥0.95, precision ≥0.90, Pearson r ≥0.5)
```

Artifacts: `fraud-gate/training/artifacts/l4_semantic_guard/` (v1) and `…/l4_semantic_guard_v4/` (v4);
compose mounts v4 at `/opt/chimera/l4` with `L4_SEMANTIC_THRESHOLD=0.65`, `TIMEOUT_MS=250`.

---

## 4. Measured state defining "bad" (v1 → v4)

### 4.1 In-domain test split — 1,257 rows (258 malicious / 999 benign), end-to-end rules+guard

| Config | TP/FP/TN/FN | Recall | FPR | Precision |
|---|---|---|---|---|
| rules only | 46/3/996/212 | 17.8% | 0.30% | 93.9% |
| v1 @0.65 | 227/10/989/31 | 88.0% | 1.00% | 95.8% |
| v4 @0.65 | 235/6/993/23 | 91.1% | 0.60% | 97.5% |
| v1 @cal 0.9760 | 203/5/994/55 | 78.7% | 0.50% | 97.6% |
| v4 @cal 0.9642 | 228/3/996/30 | 88.4% | 0.30% | 98.7% |

Semantic-only (no rules): v1 87.6%/0.70% → v4 90.3%/0.30%. Cache replay: 0/1,257 decision
mismatches; p50 45→0.98 ms (v1), 33→0.45 ms (v4). Sources: `build-check/v4-evals/`.

### 4.2 External SPML — 15,913 deduped rows, never trained on

`spml_gandalf` 4,168 (origin-familiar: training contains Lakera gandalf) vs `spml_native` 11,745
(3,372 benign + 8,373 malicious, degrees 1–10) — **native is the real generalization test**.

| Config | Recall ALL | FPR ALL | gandalf recall | native recall | native FPR |
|---|---|---|---|---|---|
| v1 @0.65 | 28.4% | 4.7% | 74.0% | 5.8% | 4.7% |
| v4 @0.65 | 40.0% | 9.9% | 86.9% | **16.7%** | **9.9%** |
| v4 @cal | 34.1% | 6.8% | 81.2% | 10.6% | 6.8% |

Per-degree native recall (v4 @0.65): deg1 15.1%, deg2 23.4%, deg3 16.5%, deg4 24.4%, deg5 17.8%,
**deg7 10.7%, deg10 9.4%**. Decision mix: native detections 1,386 CHALLENGE + 11 BLOCK — the guard
almost never escalates to BLOCK on unseen attacks (severity gap; no severity labels exist anywhere).
Sources: `build-check/v4-evals/spml_degrees_*.txt`, `pred_v4_external*.csv`.

### 4.3 Retrieval (neural RAG, opt-in) — measured, partially invalid

`BAAI/bge-small-en-v1.5` + `cross-encoder/ms-marco-MiniLM-L-6-v2`, corpus 6,146 train rows,
200 queries (seed 13), Redis 7. Base-model run (`build-check/v4-retrain/eval_neural_base.log`):

| Scenario | recall@5 vs brute-force top-10 | verdict precision@5 | majority-vote acc | p50 / p95 latency |
|---|---|---|---|---|
| full_corpus | **0.036** | 0.036 | 0.885 | **5,858 / 15,820 ms** |
| legacy_page (first_page) | 0.04 | 0.04 | 0.83 | 7,161 / 18,353 ms |
| lsh_buckets | **0.12** | 0.12 | 0.875 | 9,184 / 16,624 ms |

**The full_corpus number is a harness artifact, not model quality — see P4.** The hashed-matcher and
fine-tuned-bi-encoder runs (`retrain_v4.py --steps retrieval --finetune-retriever`) have **no recorded
result** (checked 2026-11-15; RESULTS_DOSSIER.md §5).

### 4.4 Everything else (summary; full detail in RESULTS_DOSSIER.md)

- Credit brain v2 (synthetic-only): holdout ROC .9457→.9535, PR .8697→.9189; holdout FPR 3.29→1.69%;
  CPN/approval-package approvals →0%; credit_sweep slight regression 0→3.7%.
- Card gate: **untrained** → every checkout fails closed to CHALLENGE; breaker OPEN under load
  (538 not-permitted calls); no CAPTURE settlement exercised by load tests.
- k6 (Docker VM 12 vCPU/7.6 GiB): read 48.11 req/s, clean write 14.63 req/s; write P95 530–644 ms
  (exceeds 500 ms target; global audit-chain advisory lock); 100/100 idempotent duplicates;
  recovery 42.5 s; index speedups 71.76×/184.10×/1.60×; cache hit 99.62%.
- Unit gates: 69 Java tests green pre-v4-retrieval; fraud-gate 59 pass/1 skip; ai-brain 13 pass.

---

## 5. Files that give bad results — ranked problem list

### P1 — Training distribution does not cover unseen persona jailbreaks (the core gap)

**Files:** `fraud-gate/training/prepare_l4_v4_data.py`, `fraud-gate/training/train_l4_semantic_guard.py`,
data `datasets/new_custom_datasets/out/v4/l4_v4_train.jsonl`.
**Evidence:** SPML-native recall 16.7% @0.65 (§4.2) while in-domain 91.1%. ~46% of missed native
attacks fit inside the 128-token window → genuine skill gap, not just truncation. Misses are
persona-framed ("You are FinancialGuru…", "You are Evie, the Educational Virtual Intelligence…",
"Consider yourself an AI-powered travel guide named ExploreAI…"). Training data (codesagar_v3) is
dominated by `ultrachat` benign chat + `gandalf` ignore-instructions style; the model partly learns
**origin style** (in-domain gandalf 99.1% vs deepset 77.1%).
**What a solution must address:** persona/roleplay jailbreak coverage without raising benign FPR;
origin-style de-leakage (source-balanced sampling, style augmentation, or source-adversarial training);
hard negatives that look like attacks but are benign (JBB benign-behaviors now downloaded, §8).

### P2 — 128-token head truncation hides the attack (measured, binding)

**Files:** `defense-pipeline/.../detect/WordPieceTokenizer.java:64`
(`if (ids.size() >= maxSequenceLength - 1) break;` — hard **head** truncation, tail never seen);
`OnnxSemanticInjectionGuard.java:45` (`max-sequence-length:128` default), `:111` (offline ctor 128);
`train_l4_semantic_guard.py` (`--max-length` default 128; model trained at 128).
**Evidence:** of 6,976 missed native attacks, **3,787 (54.3%) exceed 126 content tokens** vs 31.0%
of caught; missed median 1,140 chars vs 357 caught; only 6.3% of misses exceed the 2,000-char prep
cap → the **token window**, not the char cap, is binding. High-degree SPML attacks bury the injection
after a long benign preamble.
**What a solution must address:** see the whole payload under the 250 ms CPU budget. Options to
evaluate: 256-token retrain (flag exists; stopped run proves ~782 steps ≈ CPU-hours, untested);
sliding-window chunked inference with max-pooling in Java (no retrain; multiplies inference cost —
must fit 250 ms or become async); head+tail sampling; longformer-style local attention (violates
WordPiece/ONNX simplicity?); hierarchical cheap-filter→full-read cascade. Quantify the latency
trade-off on this CPU, don't assume.

### P3 — In-domain threshold calibration does not transfer to external traffic

**Files:** `fraud-gate/training/score_l4_onnx.py::choose_threshold` (lowest threshold with FPR ≤
budget on the calibration set), `prepare_l4_v4_data.py` (reserved 650-row in-domain dev half),
`train_l4_semantic_guard.py` (`--calibration-data` block).
**Evidence:** calibrated ≤0.5% dev FPR → **6.8% FPR on SPML-native benign** (228/3,372), recall
drops 16.7→10.6%. External benign text scores systematically higher than in-domain benign.
**What a solution must address:** distribution-shift-aware operating points: external-aware
calibration (a held-out *calibration* slice of external data that is then never used for testing),
conformal prediction / quantile calibration per distribution, temperature scaling, or a
shift-detector that tightens the threshold when input distribution drifts. Must not silently
consume the external test set.

### P4 — Retrieval benchmark `full_corpus` scenario is invalid (positional truncation)

**Files:** `fraud-gate/app/case_matching.py:20` (`MAX_CANDIDATES = 128`), `:290`
(`bounded = list(candidates[:MAX_CANDIDATES])` — truncates **by list position**, not similarity);
`fraud-gate/training/evaluate_case_retrieval.py:88-96,129-132` (passes all 6,146 candidates in
corpus order; ground truth at `:107-127` spans all 6,146).
**Evidence:** measured recall@5 = 0.036. Under positional truncation the expected overlap is
10 × (128/6,146) / 5 ≈ **0.042** — the measurement matches chance. The matcher never sees ~98% of
the corpus in this scenario; the number says nothing about encoder quality.
**Contrast:** `legacy_page` 0.04 is a *genuine* (intentionally weak) baseline —
`case_memory.py:190-191` `first_page` = insertion-order zrange. `lsh_buckets`
(`case_memory.py:193-208`, 12 bands × 8 sign-bits, hit-count ranked, backfilled with first_page)
is the meaningful comparison — result pending at writing.
**What a solution must address:** fix the harness (pre-rank candidates by bi-similarity before the
128-cap, or evaluate the matcher's truncation explicitly as a separate metric), then re-measure.
Decide whether `match()` should similarity-truncate instead of position-truncate (cost: encoding
all candidates — that is brute force; the production design deliberately bounds work via LSH).

### P5 — Neural RAG blend weights + latency (secondary, partially unverified)

**Files:** `fraud-gate/app/case_matching.py:318-322`
(`score = 0.55*bi + 0.35*cross + 0.10*feature`), `:113-134` (`structured_feature_similarity` —
relative numeric closeness; the eval's only shared feature is `payload_chars`), `:314` (sigmoid of
raw MS-MARCO logits), `:297-303` (bi top-20 rerank window).
**Evidence:** measured p50 **5.9 s** / p95 15.8 s per query (full_corpus); lsh_buckets p50 9.2 s.
The embedding cache is **not** the cause in this run (eval cache 8,192 ≥ corpus 6,146: 77,184 hits /
6,146 misses — one encode per corpus row). Suspected causes (verification probe pending): torch
default thread pool oversubscription (~11× CPU parallelism observed on a 10C/12T host) and
cross-encoder inference on 20 long pairs per query. The blend itself is unverified as a quality
problem — P4 masks it — but note the cross-encoder is MS-MARCO passage-ranking (out-of-domain for
jailbreak text) and a single length feature carries 10% weight against a compressed bi-similarity
range. LSH vs legacy is a real, measured 3× recall gain (0.12 vs 0.04) — both far below ceiling.
**What a solution must address:** pin torch threads / export encoders to ONNX int8 (the L4 guard
already proves single-thread ONNX runs 10–33 ms p50); size the embedding cache to the corpus;
re-calibrate blend weights on a fixed harness; consider domain-tuned cross-encoder (the fine-tuned
bge-small from `train_contrastive.py` is the first step, running now).

### P6 — Card fraud gate is untrained; the payments core fails closed

**Files:** `fraud-gate/app/card_model.py`, `onnx_card_model.py`,
`fraud-gate/training/train_creditcard_hgb.py`, `evaluate_creditcard_hgb.py`;
`fraud-gate/artifacts/` **empty**.
**Evidence:** live probe `POST /orders/{id}/authorize` → `STEP_UP`, `reasons=[GATE_TIMEOUT]`;
breaker `fraudGate` OPEN, failure_rate 100%, 538 not-permitted under load (BENCHMARK.md §7).
**Data now available:** `raw/creditcard_ulb/creditcard.csv` — 284,807 rows, sha256 in
`raw/V5_DOWNLOAD_MANIFEST.json` (HF mirror of ULB; **license caveat:** mirror tagged MIT, original
ULB is DbCL 1.0 — review before redistribution). Trainer exists and is unit-tested; **never run**.
**What a solution must address:** run the HGB path (CPU-cheap), calibrate thresholds under the
policy bands (`policy.py`: ≥0.85 VOID, ≥0.35 CHALLENGE), export ONNX variant, re-run k6 to measure
the CAPTURE path and breaker recovery. Class imbalance 492/284,807 fraud (0.17%) — PR-AUC and
cost-sensitive evaluation, not accuracy.

### P7 — No wire (PaySim) or account-opening (BAF) trainer

**Files:** `fraud-gate/training/retrain_v4.py` (wire step always skipped — no PaySim-schema
trainer); BAF catalogued in `datasets/new_custom_datasets/` but **no HF mirror found; requires
Kaggle credentials, absent on this host**.
**Data now available:** `raw/paysim/paysim.csv` — 6,362,620 rows (manifest; mirror tagged MIT,
original CC BY-SA 4.0). PaySim is for **simulated wire typology only**, never the card gate.
**What a solution must address:** a PaySim-schema trainer (sequence/aggregate features over steps,
type-conditional amounts, balance-delta consistency) + evaluation protocol; BAF acquisition path.

### P8 — English-only tokenizer; multilingual injections missed by design

**Files:** `WordPieceTokenizer.java` + `vocab.txt` (30,522 English-uncased);
`train_l4_semantic_guard.py` (WordPiece requirement).
**Evidence:** v1 missed 16 deepset rows incl. German-language injections (EVALUATION.md §4);
v4 deepset recall 77.1% — German rows still structurally hard.
**What a solution must address:** multilingual coverage under the <100M + WordPiece + Java-runtime
constraints (e.g., multilingual MiniLM/LaBSE-family distillation with a compatible vocab, or
translate-to-English augmentation at prep time — the latter needs no runtime change).

### P9 — Severity calibration gap: detections are CHALLENGE, almost never BLOCK

**Files:** `L4_InjectionLeakLayer.java` (escalate-only fusion), `ai/SeverityAdvisor.java`.
**Evidence:** SPML-native v4 detections: 1,386 CHALLENGE vs 11 BLOCK (§4.2). No severity labels
exist in any dataset (0/8,692 + SPML), so Pearson-r severity calibration is measurable only on the
synthetic battery (`AdversarialValidationTest`), not real data.
**What a solution must address:** whether BLOCK should be reachable for high-confidence semantic
detections (policy decision: false-BLOCK cost vs step-up friction), and severity-labelled data.

### P10 — Stale documentation contradicts measured state

**Files:** `README.md` "Where improvements are needed" (~line 375+): claims no artifacts bundled,
metrics NOT_MEASURED, no Maven installed — all contradicted by trained v1/v4 artifacts, measured
numbers, and green gates. `fraud-gate/training/README_V4.md` §4 retrieval tables still placeholder
at writing. **Fix:** rewrite from RESULTS_DOSSIER.md; never leave a stale claim in a resume-facing
document.

---

## 6. Root-cause evidence pack (for the frontier model)

1. **Window statistics** (token-count analysis over `out/v4/l4_v4_external.jsonl` joined to
   `pred_v4_external.csv`): missed native attacks 3,787/6,976 (54.3%) > 126 content tokens;
   caught 31.0%; missed median 1,140 chars vs caught 357; only 6.3% of misses > 2,000 chars.
2. **Per-degree collapse**: native deg7 10.7%, deg10 9.4% (v4 @0.65) — the longest, most
   obfuscated attacks are the weakest, consistent with head truncation + persona burial.
3. **Origin-style leakage**: in-domain gandalf 99.1% vs deepset 77.1%; external gandalf 86.9% vs
   native 16.7%. The model recognizes familiar attack *style*, not injection *intent*.
4. **Threshold transfer**: dev-calibrated 0.9642 → external FPR 6.8% (13.6× the 0.5% budget).
5. **Retrieval truncation arithmetic**: 0.036 measured ≈ 0.042 expected under positional 128-cap
   (P4) — benchmark bug, not encoder failure.
6. **Latency**: L4 ONNX single-thread p50 10–33 ms (fits 250 ms); neural RAG torch path p50 5.9 s
   (does not fit any synchronous budget; currently async-only, opt-in).

## 7. Questions for the frontier model

1. **v5 model recipe:** given §2 constraints and §8 data, what training-data mixture, augmentation,
   and loss design closes the persona-jailbreak gap (P1) while keeping benign FPR ≤1% on unseen
   distributions? Be specific about source balancing and hard-negative construction.
2. **Window strategy (P2):** 256-token retrain vs chunked sliding-window max-pool in Java vs
   head+tail vs cascade — which fits 250 ms on this CPU, and what is the expected recall gain from
   the 54.3% out-of-window mass? Show the latency arithmetic.
3. **Calibration under shift (P3):** design an operating-point procedure that is honest about
   external data usage (calibration slice vs test slice) and gives a defensible FPR guarantee.
4. **Retrieval (P4/P5):** the corrected benchmark design, blend-weight recalibration, and the
   cheapest path to sub-100 ms neural retrieval on CPU.
5. **Card gate (P6):** training + calibration + ONNX export plan for ULB under 0.17% imbalance,
   and the k6 verification plan for the CAPTURE path.
6. **Multilingual (P8) and severity (P9):** lowest-risk paths under the runtime constraints.
7. **Evaluation protocol:** what must v5 measure (and on which held-out sets) before any number
   goes in a resume? Proposed **goals** (not results): native recall ≥50% @ FPR ≤2%, in-domain
   recall ≥90% @ FPR ≤0.5%, retrieval p50 ≤100 ms, card gate trained + CAPTURE path load-tested.

## 8. Data downloaded for v5 (verified, NOT used in any training yet)

Manifest with sha256 + row counts: `datasets/new_custom_datasets/raw/V5_DOWNLOAD_MANIFEST.json`.

| File | Rows | Source (HF) | Intended use |
|---|---|---|---|
| `raw/creditcard_ulb/creditcard.csv` | 284,807 | David-Egea/Creditcard-fraud-detection (MIT mirror tag; original DbCL 1.0) | card HGB gate (P6) |
| `raw/paysim/paysim.csv` | 6,362,620 | theman10/paysim (MIT mirror tag; original CC BY-SA 4.0) | simulated wire only (P7) |
| `raw/jailbreakbench/harmful-behaviors.csv` | 100 | JailbreakBench/JBB-Behaviors (MIT) | L4 hard positives (P1) |
| `raw/jailbreakbench/benign-behaviors.csv` | 100 | same | L4 hard negatives (P1) |
| `raw/in_the_wild_jailbreaks/jailbreak_2023_05_07.parquet` | 666 | TrustAIRLab/in-the-wild-jailbreak-prompts (MIT) | real persona jailbreaks (P1) |
| `raw/in_the_wild_jailbreaks/jailbreak_2023_12_25.parquet` | 1,405 | same | same |
| `raw/in_the_wild_jailbreaks/regular_2023_05_07.parquet` | 5,721 | same | real benign contrast (P1) |
| `raw/in_the_wild_jailbreaks/regular_2023_12_25.parquet` | 13,735 | same | same |

**BAF (Bank Account Fraud): no HF mirror found; needs Kaggle credentials (absent).** SPML already
fetched earlier (`raw/spml/train.jsonl`, 16,012 rows, MIT) and remains the external test set.
Leakage rule for v5 prep: any new training source must be hash-deduped against test/dev/external
splits exactly as `prepare_l4_v4_data.py` does; in-the-wild jailbreaks must never overlap SPML test.

## 9. Test environment (all measurements)

Windows 11 10.0.26200 x64, Intel i5-1334U (10C/12T), 15.7 GB. JDK Temurin 21.0.13+9, Maven 3.9.9
(`C:/Users/USER/tools/`, not on PATH), Spring Boot 3.3.5. Python venv 3.13
(`build-check/fraud-gate-venv`): torch 2.15.0+cpu, transformers 5.22.2, onnxruntime 1.31.1
(CPU intraOp=interOp=1), scikit-learn 1.6.1, sentence-transformers 5.7.0; **no xgboost, no Kaggle
creds**. Load: Docker Desktop VM 12 vCPU/7.60 GiB, k6 0.55.0, PostgreSQL 15, Redis 7 (retrieval
bench on port 6399). Base encoder: local `build-check/l4_base` (4 layers/256 hidden/4 heads,
11,171,074 params, English-uncased WordPiece).

## 10. Number → artifact map

| Claim | Artifact |
|---|---|
| In-domain v1/v4 end-to-end + calibrated | `build-check/v4-evals/score_*.txt`, `java_*.log` |
| Semantic-only per-source | `build-check/v4-evals/probs_v1_test.json`, `probs_v4_test.json` |
| Cache replay | `build-check/v4-evals/cache_replay_*.json` |
| SPML overall/per-degree | `build-check/v4-evals/pred_v4_external*.csv`, `spml_degrees_*.txt`, `external_breakdown.py` |
| Window statistics | token-count analysis over `out/v4/l4_v4_external.jsonl` + `pred_v4_external.csv` (dossier §3.2) |
| Retrieval base numbers | `build-check/v4-retrain/eval_neural_base.log` (+ `retrieval_neural_base.json` on completion) |
| Credit v1/v2 | `build-check/v4-retrain/credit_v2_report.json`, `ai-brain/models/*.json` |
| k6 / breaker / outbox | `build-check/bench/*.json`, `metrics-final-*.txt`, BENCHMARK.md |
| Downloads | `datasets/new_custom_datasets/raw/V5_DOWNLOAD_MANIFEST.json` |
| Stopped 256-token run | `build-check/l4_candidate_recall/` (empty checkpoints only) |