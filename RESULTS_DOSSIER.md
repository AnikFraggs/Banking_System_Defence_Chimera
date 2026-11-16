# CHIMERA Checkout Shield — Full Honest Results Dossier

> **2026-11-16 L4 decision:** v8 trained from v6 with full replay + 3,000 new ProtectAI-scored rows. **Not adopted:** new-holdout FPR 3.6% exceeds 2%; paired recall improves but external ROC-AUC regresses. CPU tokenize+int8 P95 13.31ms; Java G1 not run after offline rejection. Both existing baseline and deployed artifacts remain untouched. See [MODEL_BENCHMARKS.md §3.5](MODEL_BENCHMARKS.md) for the full paired protocol and why its stricter calibration results must not be mixed with historical v6 scores.

> **2026-11-16 L4 v9 decision:** the Qwen-adapted v9 (v8-initialized dual-view MiniLM + reliability-gated ProtectAI/v6 KD + training-side grouped lexical stacker) was trained on the ROCm GPU and benchmarked vs v6/v8/ProtectAI under a locked 1%-calibration/2%-test protocol. **Not adopted:** the hybrid keeps FPR≤2% and ~13ms CPU P95 but recall regresses vs v6 and v8; the stacker overfits its meta split and the paired/B view learns nothing usable (ProtectAI-B external FPR .9675). Plain neural v9-A beats v6 on every holdout but trails v8 on external SPML (.116 vs .210); ProtectAI external recall .968 dwarfs every 33M student. v6 remains the best prior-protocol deployable student; no baseline/deployed artifact changed. Research-only (No Robots CC-BY-NC-4.0); hybrid not in Java. See [MODEL_BENCHMARKS.md §3.6](MODEL_BENCHMARKS.md).

> **2026-11-16 monitoring verification:** ten Prometheus targets UP; 71 live dashboard/rule expressions pass the metric contract; 17 alert rules healthy; four alert fixtures pass. The initial bounded settlement test captured 139/142 orders, with all 139 receipts valid; three `GATE_TIMEOUT` challenges mean the capture-failure target failed (2.11%). The same bounded run repeated after model jobs finished passed: **160/160 captures and valid receipts**, zero HTTP failures, authorize P95 **129.88ms**. Both results are retained; these are not production-capacity claims. See [BENCHMARK.md](BENCHMARK.md) and [observability/README.md](observability/README.md). Browser rendering and a real kind cluster remain unverified. These results supersede blanket claims below that the mounted card gate cannot CAPTURE.

> **UPDATE 2026-11-14:** the card gate (#12) is now **TRAINED on real ULB data** and the wire gate
> (#17) now **has a trainer + measured PaySim artefact**; L4 v5 (#5/#6 successor) is fine-tuned.
> The "TOOLING — NOT TRAINED / NO TRAINER EXISTS / artifacts empty" rows and the §1 bottom line
> ("card gate untrained") below are **stale**. Measured rival benchmarks (XGBoost/LightGBM, ProtectAI
> DeBERTa-v3), provenance and CIs are in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md). This dossier's
> environment (venv 3.13 / torch 2.15) differs from the benchmark host (system 3.14.6 / torch 2.13);
> numbers are not mixed across environments.
>
> **UPDATE 2026-11-15** (benchmark host; full tables and CIs in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md)):
> - **Card gate (#12): trained, not promoted.** The real ULB model is
>   `fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib` (gitignored). The mounted
>   `fraud-gate/artifacts/creditcard_hgb.joblib` is still a synthetic toy that also expects `Time`, so
>   every card score fails `INVALID_FEATURES` and the gate fails closed to CHALLENGE (§6).
> - **Triage (#23) is now a hybrid RAG** (BM25 + bge-small ONNX int8 + RRF + a fitted reranker),
>   unioned with the regex KB and escalate-only. Attack escalation 0.171 → 0.627; benign escalation
>   0.0086 → 0.0159 (§5.2).
> - **Credit v3 (LightGBM, #25b) is the default**; v2 stays available for rollback (§4.4).
> - **L4 v6** (distilled 33M MiniLM, #6b) is the best deployable guard, but G1 is still not met. v5
>   regressed against v4, and v7/v7b and the ensembles were not adopted.
> - The case-memory bi-encoder fine-tune has **no recorded result** (§5); the earlier bottom line
>   claimed one.
> - Test gates were re-run (§8). Open items, including genuine datasets still missing, are in §9.

**Purpose:** complete inventory of every defense layer and every model, with training status and
every measured number, for external gap analysis. Compiled 2026-11-14; updated 2026-11-15 with
benchmark-host results, which are labelled as such.

**Rules of this document:** every number is measured. §10 maps each to its source file; the few
console-only runs (no raw log kept) say so where they are quoted.
Nothing is a target dressed as a result. Components that were never trained say so. Synthetic-data
metrics measure recovery of the generator's signal, not real-world fraud quality. PayPal is stub-only;
no real cards, accounts, or production deployment is claimed anywhere.

**Test environment (dossier host; parts marked 2026-11-15 use the benchmark host, see MODEL_BENCHMARKS.md):** Windows 11 10.0.26200 x64, Intel i5-1334U (10C/12T), 15.7 GB.
Java: Temurin JDK 21.0.13+9, Maven 3.9.9, Spring Boot 3.3.5. Python: venv 3.13, torch 2.15.0+cpu,
transformers 5.22.2, onnxruntime 1.31.1 (CPU, intraOp=interOp=1), scikit-learn 1.6.1,
sentence-transformers 5.7.0. Load tests: Docker Desktop VM 12 vCPU / 7.60 GiB, k6 0.55.0,
PostgreSQL 15, Redis 7. Retrieval benchmarks: Redis 7 container, port 6399.

---

## 1. Every layer and model — status inventory

Status legend: **RULES** = deterministic, no training · **TRAINED** = trained/fine-tuned in this
project with a measured artifact · **PRETRAINED** = third-party checkpoint used as-is (opt-in) ·
**STUB** = deterministic placeholder, no real model · **TOOLING** = script exists, unit-tested, never
run on real data, no artifact.

| # | Component | File | Status | Artifact on disk | Fallback when absent/error |
|---|---|---|---|---|---|
| 1 | L1 IP reputation | `defense-pipeline/.../layers/L1_IpReputationLayer.java` | RULES (static denylist, 2 IPs) | n/a | missing IP → CHALLENGE |
| 2 | L2 role/status | `layers/L2_RoleStatusLayer.java` | RULES (role→purpose allowlist) | n/a | — |
| 3 | L3 purpose | `layers/L3_PurposeLayer.java` | RULES (known purposes + withdraw/beneficiary heuristic) | n/a | — |
| 4 | L4 injection/leak: Unicode/bidi/homoglyph/nested-encoding/phrasing scanner + canaries | `layers/L4_InjectionLeakLayer.java`, `detect/InjectionScanner.java`, `detect/CanaryTokenRegistry.java` | RULES | n/a | canary → QUARANTINE 0.98; scan hit ≥0.7 → BLOCK |
| 5 | L4 semantic guard v1 | `detect/OnnxSemanticInjectionGuard.java` + `fraud-gate/training/artifacts/l4_semantic_guard/` | **TRAINED** (fine-tuned local bert-mini, int8 ONNX) | yes, 11.37 MB | not configured → PASS fail-open (rules still run); configured-but-unavailable/timeout/error → **fail-closed CHALLENGE** |
| 6 | L4 semantic guard v4 | same class + `artifacts/l4_semantic_guard_v4/` | **TRAINED** (v4 data recipe) | yes, 11.37 MB | same as v1 |
| 6b | L4 semantic guard v6 (best candidate, not deployed) | `build-check/l4_distill/out_minilm_l12_v2/` | **TRAINED 2026-11-14** (MiniLM-L12, 33.36M params, distilled from ProtectAI DeBERTa-v3 on the RX 9070 XT; MODEL_BENCHMARKS.md §3.1) | yes, int8 ONNX, gitignored; **not bundled or wired** — its operating cut (≈3e-6) is fragile | n/a until wired |
| 7 | L4 verdict cache | `detect/SemanticVerdictCache.java` | RULES (LRU, SHA-256 keys) | n/a | capacity 0 disables; errors/timeouts never cached |
| 8 | L5 human verification | `layers/L5_HumanVerificationLayer.java` | RULES (ghost-text challenge) | n/a | CHALLENGE unless passed |
| 9 | L6 deception vault | `layers/L6_DeceptionVaultLayer.java` | RULES | n/a | quarantine on self_heal_failed |
| 10 | Severity advisor | `ai/SeverityAdvisor.java` (LOCAL_ONLY) / `platform-api/.../AiBrainSeverityAdvisor.java` | RULES (max-fusion, escalate-only) | n/a | brain unreachable → local severity (`fromFallback`) |
| 11 | Pipeline fail-safe | `DefensePipeline.java` | RULES | n/a | any layer exception → CHALLENGE `layer_error_fail_safe` |
| 12 | Card fraud model | `fraud-gate/app/card_model.py` (HistGradientBoosting; ONNX variant `onnx_card_model.py`) | **TRAINED 2026-11-14, NOT PROMOTED** (real ULB, 29 feats; MODEL_BENCHMARKS.md §1) | trained: `fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib` (gitignored). Mounted: `fraud-gate/artifacts/creditcard_hgb.joblib` = **synthetic toy** (30 feats incl. `Time`) | absent → `MODEL_UNAVAILABLE`, `/ready` 503; feature mismatch → `INVALID_FEATURES` (today: toy vs the 29-feature simulator vector); both score 0.5 → **fail-closed CHALLENGE** |
| 13 | Device/velocity "temporal graph features" | `fraud-gate/app/temporal_graph.py`, `rolling_counters.py` | RULES (no GNN) | n/a | Redis absent → in-request history |
| 14 | Behavioral biometrics | `fraud-gate/app/biometrics.py` | RULES (timing/mouse uniformity) | n/a | — |
| 15 | Evidence / image forensics | `fraud-gate/app/evidence.py`, `image_forensics.py` | RULES (deterministic heuristics) | n/a | — |
| 16 | Fraud-gate policy | `fraud-gate/app/policy.py` | RULES (bands: ≥0.85 VOID, ≥0.35 CHALLENGE, else CAPTURE) | n/a | — |
| 17 | Wire (PaySim) model | `fraud-gate/training/train_paysim_wire.py` + `bench_wire_fraud.py` | **TRAINED 2026-11-14** (synthetic PaySim, 10 feats; MODEL_BENCHMARKS.md §2) | yes, `fraud-gate/training/benchmarks/wire/paysim_wire_hgb.joblib` (gitignored); **no runtime consumer** in `fraud-gate/app/` | synthetic only — not real wire-fraud quality |
| 18 | Account-opening (BAF) model | — | **TOOLING** catalogued, no trainer wired | no | — |
| 19 | Async debate (prosecutor/defense/judge) | `fraud-gate/app/debate.py`, `worker.py` | **STUB** (deterministic arguments + rule judge; optional HTTP backend `EXPLANATION_BACKEND_URL`) | n/a | template fallback; `score_delta` clamped **±0.05, informational only — never changes pre-capture score** |
| 20 | Case memory RAG — hashed matcher (default) | `fraud-gate/app/case_matching.py` `HashedCaseMatcher` | RULES (SHA-256 bag-of-words 128-d, `sha256-bow-128-v1`) | n/a | marked `fallback=True` |
| 21 | Case memory RAG — neural matcher (opt-in) | `SentenceTransformerCaseMatcher` | **PRETRAINED** `BAAI/bge-small-en-v1.5` (384-d) + `cross-encoder/ms-marco-MiniLM-L-6-v2`; a bi-encoder fine-tune was attempted but has **no recorded result** (§5) | HF cache only (no fine-tuned dir exists) | requires both `CASE_BI_ENCODER_MODEL`+`CASE_CROSS_ENCODER_MODEL`, else hashed |
| 22 | Case memory store + LSH candidate generation | `fraud-gate/app/case_memory.py` | RULES (Redis, Lua CAS feedback, 12×8-bit LSH buckets) | n/a | `candidate_strategy="first_page"` = legacy behavior |
| 23 | AI-brain triage `/v1/triage` | `ai-brain/app.py` + `ai-brain/rag_engine.py` | **HYBRID RAG, deployed 2026-11-15**: BM25 + `BAAI/bge-small-en-v1.5` ONNX int8 (pretrained, as-is) + RRF + a **fitted** 5-feature logistic reranker, unioned with the 7-class regex KB; risk is still the hand-weighted logistic; never calls an LLM | reranker `ai-brain/models/rag_reranker.json`; encoder `ai-brain/models/bge_small/model_int8.onnx` (gitignored, 34 MB) | encoder or reranker missing → regex-only, shown as `rag_hybrid_loaded: false` in `/health`; hybrid hits only escalate |
| 24 | AI-brain credit scorer v1 | `ai-brain/credit_brain.py` + `models/credit_brain_v1.json` | **TRAINED on synthetic data** (standardized LR, 34 features) | yes | missing model → fail-closed manual_review; never auto-declines |
| 25 | AI-brain credit scorer v2 (rollback) | `models/credit_brain_v2.json` | **TRAINED on synthetic + ring-grouped adaptive mix** | yes | same |
| 25b | AI-brain credit scorer v3 (**default since 2026-11-15**) | `models/credit_brain_v3.json`; trainer `ai-brain/training/train_credit_brain_v3.py` | **TRAINED on synthetic data** (LightGBM, 300 trees, served as stdlib JSON; Saabas reason codes) | yes (665,786 bytes) | same; v1/v2 load via `CREDIT_BRAIN_MODEL_PATH` |
| 26 | Verdict LLM (LoRA) | `fraud-gate/training/train_lora_verdicts.py` | **TOOLING — never run** (needs local 3–7B causal model) | **no adapter anywhere** | — |
| 27 | Safe-LCB step-up policy | `fraud-gate/training/train_safe_lcb.py`, runtime `app/safe_lcb.py` | **TOOLING — never run**; runtime loader opt-in, tighten-only | **no policy artifact** | absent → default policy |
| 28 | Java→fraud-gate client | `platform-api/.../FraudGateClient.java`, `ResilientFraudGateConfig.java` | RULES (300 ms budget, circuit breaker) | n/a | timeout/error → CHALLENGE score 0.5 (`GATE_TIMEOUT`/`GATE_ERROR`/`GATE_CIRCUIT_OPEN`) |
| 29 | Java→ai-brain client | `platform-api/.../AiBrainClient.java` | RULES (2 s connect / 4 s read) | n/a | conservative local fallback |

**Bottom line (updated 2026-11-15):** trained and measured: the **L4 semantic guard** (v1, v4, v5 and
the distilled **v6** candidate), the **card gate** (real ULB HGB, **not promoted**), the **wire gate**
(synthetic PaySim HGB, no runtime consumer), the **credit brain** (v1/v2/v3, synthetic only; v3 is
the default) and the **triage reranker** (a 5-feature logistic over pretrained retrievers).
Everything else is rules, pretrained-as-is, stubs, or unrun tooling. The case-memory bi-encoder
fine-tune has no recorded result (§5). Rival benchmarks and provenance are in
[`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md). Two facts dominate:
- the card gate still fails closed on every order, because the mounted artifact is the synthetic
  toy (§6);
- **no deployable L4 model meets G1**: v6 reaches SPML-native recall 0.409, against 0.827 for the
  184M ProtectAI rival.

---

## 2. L4 semantic guard — training facts

| | v1 | v4 |
|---|---|---|
| Version | `l4-semantic-codesagar-v1` | `l4-semantic-v4` |
| Base | local `build-check/l4_base`: compact BERT, 4 layers / 256 hidden / 4 heads, English-uncased WordPiece 30,522 | same |
| Params | 11,171,074 | 11,171,074 |
| Export | FP32 ONNX opset 17 → dynamic int8 (11.37 MB); max_length **128 tokens** | same |
| Train rows | 4,332 (internal split of 5,433 train-split rows) | 6,248 expanded / **5,370 unique** |
| Internal held-out | 1,101; eval_loss **0.0612** | 1,397; eval_loss **0.0489** |
| artifact sha256 | `6c4e951120b9d5d1…` | `591fdb04b7ae63b2…` |
| Data | codesagar_v3 train split, ≤2000 chars (713 longer rows **dropped**) | v4 recipe below |

v4 data recipe (`prepare_l4_v4_data.py`, manifest `datasets/new_custom_datasets/out/v4/MANIFEST_V4.json`):
- >2000-char rows **truncated, not dropped** (recovers 188 malicious jackhhao roleplay rows v1 never saw).
- Weak-source oversampling (`repeat` 2: deepset both labels, jackhhao-malicious, synthetic), expanded
  **after** the grouped split so held-out stays clean.
- Half of dev mined with v1: its 20 errors (14 FN / 6 FP) added at `repeat` 3; other dev half (650 rows)
  reserved for threshold calibration only.
- Zero exact-normalized overlap train↔test/calib/external (verified; prep raises on leakage).
- Thresholds: deployed 0.65; calibrated on reserved dev half at ≤0.5% FPR → **v1 0.9760138809890777,
  v4 0.9642237466520428**.

Internal eval_loss values are on different internal splits — the comparable numbers are below.

### 2.1 End-to-end test split (1,257 rows: 258 malicious / 999 benign; rules + guard, Java harness)

| Config | TP | FP | TN | FN | Recall (Wilson 95%) | FPR (Wilson 95%) | Precision |
|---|---|---|---|---|---|---|---|
| Rules only (no model) | 46 | 3 | 996 | 212 | 17.8% (13.6–23.0) | 0.30% (0.1–0.9) | 93.9% |
| v1 @0.65 | 227 | 10 | 989 | 31 | 88.0% (83.4–91.4) | 1.00% (0.5–1.8) | 95.8% |
| **v4 @0.65** | 235 | 6 | 993 | 23 | **91.1% (87.0–94.0)** | **0.60% (0.3–1.3)** | **97.5%** |
| v1 @calibrated 0.9760 | 203 | 5 | 994 | 55 | 78.7% (73.3–83.2) | 0.50% (0.2–1.2) | 97.6% |
| **v4 @calibrated 0.9642** | 228 | 3 | 996 | 30 | **88.4% (83.9–91.7)** | **0.30% (0.1–0.9)** | 98.7% |

Sources: `build-check/v4-evals/score_*.txt`, `java_*.log`; rules-only from
`datasets/new_custom_datasets/EVALUATION.md` §3 (same harness, pre-v4).

### 2.2 Semantic-only per-source (model without rules; 1,257 test rows, threshold 0.65)

| sub_source | v1 recall | v4 recall | v1 FP | v4 FP |
|---|---|---|---|---|
| deepset/prompt-injections (48 mal / 55 ben) | 66.7% | **77.1%** | 0 | 0 |
| jackhhao/jailbreak-classification (89 mal / 96 ben) | 87.6% | **89.9%** | 4 | **1** |
| Lakera/gandalf (112 mal) | 99.1% | 99.1% | 0 | 0 |
| synthetic (9 mal / 5 ben) | 55.6% | 55.6% | 1 | **0** |
| ultrachat_200k (843 ben) | FPR 0.24% | FPR 0.24% | 2 | 2 |
| **ALL** | 87.6% / FPR 0.70% | **90.3% / FPR 0.30%** | 7 | 3 |

Source: `build-check/v4-evals/probs_v1_test.json`, `probs_v4_test.json`.
Known weakness: English-only tokenizer — German-language deepset injections are missed by design.

### 2.3 Verdict cache (protection unchanged, latency improved)

Bounded LRU (default 4,096, `L4_SEMANTIC_CACHE_SIZE`, max 100,000, 0 disables), SHA-256(exact text)
keys, raw text never stored, timeouts/errors never cached. Replay pass over the same 1,257 rows:

| | v1 first pass | v1 replay | v4 first pass | v4 replay |
|---|---|---|---|---|
| p50 per payload | 45 ms | **0.98 ms** | 33 ms | **0.45 ms** |
| p95 | 95 ms | 10.1 ms | 80 ms | 3.9 ms |
| max | 668 ms | 65.8 ms | 448 ms | 17.4 ms |
| decision mismatches | — | **0 / 1,257** | — | **0 / 1,257** |

Hits 1,256/1,256 eligible (one blank payload short-circuits). Cache only helps repeated payloads;
first-seen pays full inference. Earlier idle-host runs measured p50 10–20 ms — latency is host-load
dependent. All first-pass rows stayed under the 250 ms production timeout except rare outliers
(max 668 ms on a loaded host; production timeout would fail-closed those to CHALLENGE).

---

## 3. External held-out: SPML (the generalization test)

Dataset: `reshabhs/SPML_Chatbot_Prompt_Injection` (HF, MIT), fetched to
`datasets/new_custom_datasets/raw/spml/train.jsonl` (16,012 rows). After canonical dedup against all
existing splits: **15,913 rows** (98 dropped as overlap). Never trained on.
- `spml_gandalf` 4,168 rows: all malicious, degrees 1–5. **Origin-familiar** (training data contains
  Lakera gandalf) — treat as sanity, not generalization.
- `spml_native` 11,745 rows: 3,372 benign (degree 0) + 8,373 malicious, degrees 1,2,3,4,5,7,10.
  **The genuinely unseen distribution.**

End-to-end (rules + guard), Java harness, timeout 1000 ms for eval (measures skill, not timeouts):

| Config | Recall ALL (Wilson 95%) | FPR (Wilson 95%) | gandalf recall | native recall | native FPR |
|---|---|---|---|---|---|
| v1 @0.65 | 28.4% (27.6–29.2) | 4.7% (4.0–5.5) | 74.0% | **5.8%** (5.3–6.3) | 4.7% |
| v4 @0.65 | **40.0%** (39.2–40.9) | 9.9% (9.0–11.0) | **86.9%** | **16.7%** (15.9–17.5) | 9.9% |
| v4 @calibrated 0.9642 | 34.1% (33.3–34.9) | 6.8% (6.0–7.7) | 81.2% | 10.6% (10.0–11.3) | 6.8% |

Confusions: v1 3565/159/3213/8976 · v4 5021/335/3037/7520 · v4cal 4274/228/3144/8267 (TP/FP/TN/FN).
Latency: v1 p50 32 / p95 85 / max 1069 ms; v4 p50 22 / p95 49 / max 277 ms; v4cal p50 13 / p95 37 /
max 520 ms. (v1's max exceeds the 1000 ms eval timeout; any timed-out row fails closed to CHALLENGE
and is counted as a detection. Per-row reasons are not in the prediction CSV, so the exact timeout
count is unrecorded — at most a handful given p95=85 ms.)

**Honest reading:** v4 improves external recall at every operating point, but FPR rises too. The
in-domain calibrated threshold (≤0.5% dev FPR) **does not transfer**: external FPR is 6.8%. Both
models are weak on truly unseen jailbreak distributions; the in-domain 91.1% is an upper bound
inflated by origin-style leakage (gandalf 99.1% in-domain).

### 3.1 Where it fails: per-degree recall (malicious rows)

| source | degree | n | v1 @0.65 | v4 @0.65 | v4 @calibrated |
|---|---|---|---|---|---|
| gandalf | 1 | 834 | 80.1% | 89.4% | 85.1% |
| gandalf | 2 | 834 | 74.9% | 86.7% | 80.3% |
| gandalf | 3 | 834 | 73.7% | 86.6% | 80.6% |
| gandalf | 4 | 834 | 70.1% | 86.1% | 80.0% |
| gandalf | 5 | 832 | 70.9% | 85.9% | 79.9% |
| native | 1 | 1,675 | 7.3% | 15.1% | 10.1% |
| native | 2 | 836 | 8.3% | 23.4% | 16.6% |
| native | 3 | 1,675 | 5.1% | 16.5% | 10.1% |
| native | 4 | 836 | 9.4% | 24.4% | 16.7% |
| native | 5 | 1,675 | 5.1% | 17.8% | 11.3% |
| native | 7 | 838 | **2.4%** | **10.7%** | **5.6%** |
| native | 10 | 838 | **2.5%** | **9.4%** | **4.3%** |

Benign native FPR: v1 4.7% (159/3,372) · v4 9.9% (335/3,372) · v4cal 6.8% (228/3,372).
Decision mix (v4 @0.65): gandalf detections 2,510 CHALLENGE + 1,114 BLOCK; native detections
1,386 CHALLENGE + 11 BLOCK — i.e. nearly all semantic detections are step-up, not block.
Full CIs: `build-check/v4-evals/spml_degrees_v1_v4.txt`, `spml_degrees_v4cal.txt`.

### 3.2 Why it fails (measured analysis)

1. **128-token window.** The guard reads only the first 128 WordPiece tokens. Of 6,976 missed native
   attacks, **3,787 (54.3%) exceed 126 content tokens** (vs 31.0% of caught ones). Missed payloads
   median 1,140 chars vs 357 for caught. High-degree SPML attacks are persona jailbreaks that bury
   the injection after a long benign preamble — outside the window. Example misses (degree 7/10):
   "You are an AI assistant named FinancialGuru…", "You are Evie, the Educational Virtual
   Intelligence…", "Consider yourself an AI-powered travel guide named ExploreAI…".
   The remaining ~46% of misses fit inside the window → genuine model-skill gap on persona-style
   jailbreaks, which are underrepresented in codesagar training data.
2. **Threshold transfer failure.** Calibrated on in-domain dev; external benign text scores higher
   (FPR 6.8% vs 0.5% target). No external calibration was performed (would touch the held-out set).
3. **Fallback behavior.** Guard disabled → PASS (rules still run). Guard configured but
   unavailable/timeout/error → fail-closed CHALLENGE. In these evals the guard was loaded and
   `available=true` for every run; no unavailable-guard fallback occurred. Timeout fallbacks are
   possible only in the v1 run (max 1069 ms > 1000 ms eval timeout) and are uncounted per-row.

Sources: `build-check/v4-evals/external_breakdown.py` output, `spml_degree_analysis.py` output,
token-count analysis over `l4_v4_external.jsonl` + `pred_v4_external.csv`.

---

## 4. Credit brain (SYNTHETIC DATA ONLY — not real-world credit-fraud quality)

Data: self-generated `datasets/synthetic_credit_boost/` (generator + manifest in that folder;
no SSN/CPN-like strings). 34 features, standardized logistic regression exported to JSON
(stdlib inference, readable reason codes). HistGradientBoosting trained as capacity comparison only,
**not shipped**.

- v1: main train split only; thresholds on val (FPR target 0.5%, recall target 95%).
- v2: adds a **ring-grouped half** of the adaptive-seller set to training (sha256(ring_id) bucket;
  a ring never straddles train/holdout). Other half = untouched 4,920-row holdout (298 fraud).
  v1 scored on the same holdout for comparison. v2 thresholds: t_low 0.1116, t_high 0.2019.

### 4.1 Ranking (AUC)

| Split | v1 ROC / PR | v2 ROC / PR | HGB v2 (not shipped) |
|---|---|---|---|
| main test (8,028) | 0.9756 / 0.9595 | 0.9733 / 0.9576 | 0.9777 / 0.9583 |
| adaptive ring holdout (4,920) | 0.9457 / 0.8697 | **0.9535 / 0.9189** | 0.9648 / 0.9348 |
| val | 0.9760 / 0.9595 | 0.9779 / 0.9597 | — |

### 4.2 End-to-end decisions (shipped policy)

| Metric | v1 | v2 |
|---|---|---|
| Main test recall (any action), n=8,028 / 651 fraud | 95.24% (93.3–96.6) | 95.24% (93.3–96.6) |
| Main test FPR (any action) | 3.74% (3.3–4.2) | **1.99% (1.7–2.3)** |
| Holdout recall (any action), n=4,920 / 298 fraud | 84.56% (80.0–88.2) | **89.60% (85.6–92.6)** |
| Holdout FPR (any action) | 3.29% (2.8–3.8) | **1.69% (1.4–2.1)** |
| Holdout manual-review precision | 80.61% | 81.94% |

(v1 was also scored on the full 10,000-row adaptive set in its own report: recall 85.96%, FPR 3.03% —
different population; the holdout comparison above is the apples-to-apples one.)

### 4.3 Per-typology on the holdout (approve rate / manual-review rate)

| typology | n | v1 approve | v2 approve | v1 review | v2 review |
|---|---|---|---|---|---|
| fraud_approval_package | 50 | 4.0% | **0.0%** | 88.0% | 100% |
| fraud_cpn_synthetic | 98 | 5.1% | **0.0%** | 91.8% | 100% |
| fraud_credit_sweep | 54 | 0.0% | 3.7% | 94.4% | 88.9% |
| fraud_tradeline_boost | 75 | 25.3% | **10.7%** | 68.0% | 77.3% |
| legit_improver | 440 | 93.6% | **96.1%** | 2.1% | 2.7% |
| legit_newcomer | 494 | 96.6% | 98.6% | 1.6% | 1.2% |
| legit_prime | 2,402 | 98.8% | 99.0% | 0.8% | 0.8% |
| legit_rebuilder | 676 | 91.3% | **97.3%** | 1.9% | 1.6% |
| legit_thin_family_au | 631 | 96.8% | 98.3% | 1.4% | 1.3% |

v2 was the default until 2026-11-15, when v3 replaced it (§4.4). Triage KB gained CB-CPN
(weight 0.9) and CB-TL (0.8) entries; triage risk stays hand-weighted (7 KB classes), and since
2026-11-15 its retrieval adds a hybrid RAG with a fitted reranker (§5.2). Sources:
`datasets/synthetic_credit_boost/TRAINING_REPORT.json` (v1),
`build-check/v4-retrain/credit_v2_report.json` (v2 + comparison).

### 4.4 v3 — LightGBM served as stdlib JSON (default since 2026-11-15)

Trainer `ai-brain/training/train_credit_brain_v3.py`. It uses exactly the v2 splits and refuses to
run on a mismatch. Both columns below are from MODEL_BENCHMARKS.md §4.2 (benchmark host); the v2
values agree with §4.2 here. End-to-end through `CreditBrain.assess`, hard flags included:

| Metric | v2 LR | v3 LGBM |
|---|---|---|
| Test recall / FPR (any action) | 0.952 / 0.0199 | 0.952 / **0.0184** |
| Adaptive holdout recall (any action) [Wilson 95%] | 0.896 [0.856–0.926] | **0.926 [0.891–0.951]** |
| Adaptive holdout FPR (any action) | 0.0169 | **0.0151** |
| Adaptive holdout PR-AUC | 0.9189 | **0.9369** |
| Unseen-seed stress recall: fresh rings / stealth graft | 0.902 / 0.894 | **0.931 / 0.931** |
| `assess` p50 / p99, single row | 0.0107 / 0.0164 ms | 0.2047 / 0.3949 ms |

- v3 improves recall and any-action FPR together, which meets the adoption rule.
- Trade-off: manual-review FPR rises slightly (test 0.0159 vs 0.0133), because more v3 flags land
  in the review band.
- v3 thresholds, chosen on val with the v2 rule: t_low 0.010413, t_high 0.014313.
- The stress sets come from the same generator (unseen seed 777001). This is **synthetic data only**.
- Source: `ai-brain/benchmarks/credit_v3/credit_v3_benchmark.{json,md}`.

---

## 5. RAG / case memory — retrieval improvements and measurements

Changes shipped (all unit-tested):
1. **LSH candidate generation** (`case_memory.py`): legacy behavior loaded only the first 128
   archetype ids — the rest were invisible. v4: 12 bands × 8 sign bits over the 128-d hashed vector
   (shake_128-seeded projections), collision-count ranking, `rebuild_buckets()` backfill,
   `candidate_strategy="first_page"` reproduces legacy.
2. **Embedding cache** (neural matcher): candidate embeddings cached by SHA-256(text), bounded LRU
   (`CASE_EMBEDDING_CACHE_SIZE`, default 4096); previously all candidates re-encoded per query.
3. **Rerank window**: cross-encoder scores only bi-encoder top `CASE_RERANK_TOP_K` (default 20)
   instead of all 128 candidates.

Fine-tune: `train_contrastive.py` (MultipleNegativesRankingLoss) on 1,521 train-split pairs
(`build_retrieval_pairs.py`, seed 13, same sub_source+label groups; telemetry = payload_chars only,
no label leakage), base `BAAI/bge-small-en-v1.5`, 1 epoch, CPU.

Benchmark harness: `evaluate_case_retrieval.py` — real Redis 7, 6,146-archetype corpus from
text_train, 200 text_test queries (seed 13), ground truth = brute-force matcher-native top-10.
**Caveat:** verdicts are L4 labels mapped to FRAUD/BENIGN on real payload text — this measures the
retrieval machinery, not analyst-confirmed fraud-case similarity.

### 5.1 Measured — neural base models (bge-small-en-v1.5 + ms-marco-MiniLM-L-6-v2, as-is)

Source: `build-check/v4-retrain/retrieval_neural_base.json` (200 queries, corpus 6,146, Redis 7,
embedding cache 8,192: **77,184 hits / 6,146 misses** — each corpus vector encoded exactly once,
cache working; corpus insert 1,042.5 s).

| Scenario | recall@5 vs brute-force top-10 | verdict precision@5 | majority-vote acc@5 | p50 / p95 / max latency (ms) |
|---|---|---|---|---|
| full_corpus | 0.036 ⚠ invalid | 0.036 | 0.885 | 5,858 / 15,820 / 30,936 |
| legacy_page (first_page) | 0.04 | 0.04 | 0.83 | 7,161 / 18,353 / 31,817 |
| lsh_buckets | **0.12** | 0.12 | 0.875 | 9,184 / 16,624 / 37,399 |

**⚠ The full_corpus scenario is invalid as constructed (benchmark bug, not model quality).**
`case_matching.py:20` caps candidates at `MAX_CANDIDATES = 128` and `match()` (`:290`) truncates
**by list position**. The harness passes all 6,146 candidates in corpus order, so the matcher only
ever sees corpus rows 0–127 while ground truth spans all 6,146. Expected recall under that
truncation ≈ 10 × (128/6,146) / 5 ≈ **0.042** — the measured 0.036 matches chance. Fix (v5): pre-rank
candidates by bi-similarity before the cap, or report truncation as its own metric.

**Honest reading of the valid scenarios:** LSH candidate generation triples recall vs legacy
insertion-order paging (0.12 vs 0.04) — the shipped improvement is real but modest; both are far
below the brute-force ceiling, and the 128-candidate cap bounds all of them. Majority-vote verdict
accuracy (0.83–0.885) is much healthier than exact-case recall: retrieved cases tend to share the
query's label even when they are not the nearest neighbors. **Latency is the headline problem:**
p50 5.9–9.2 s per query on this CPU (torch default thread pool on 10C/12T; cross-encoder on 20 long
pairs per query). The neural path is opt-in and async-only in production; it is not usable
synchronously at this latency. v5 fixes: thread pinning / ONNX export, harness fix, blend-weight
recalibration (`case_matching.py:318-322` — 0.55 bi + 0.35 cross + 0.10 feature; the single
`payload_chars` feature and out-of-domain MS-MARCO cross-encoder are suspects, unverified).

Hashed-matcher and fine-tuned-bi-encoder runs: **no recorded result** (checked 2026-11-15). They
were started via `retrain_v4.py --steps retrieval --neural-retrieval --finetune-retriever` on the
original host:
- `build-check/v4-retrain/retrieval-finetune.log` stops after model load;
- `MANIFEST.json` records only the `retrieval-pairs` step;
- no `retrieval_hashed.json`, `retrieval_neural.json` or `bge-small-chimera/` output exists.

Re-run them before quoting any number. The labelled relevance benchmark (G4) is also still not run.

### 5.2 Triage RAG in ai-brain `/v1/triage` — hybrid retrieval (measured, deployed 2026-11-15)

This is separate from the case memory above. Full architecture, per-source tables and protocol:
MODEL_BENCHMARKS.md §5.1.
- **Pipeline** (`ai-brain/rag_engine.py`, all offline):
  - canonicalize (NFKC, zero-width strip, URL/HTML decode, `<email>`/`<pan>` redaction);
  - BM25 plus bge-small-en-v1.5 (ONNX int8, CLS 384-d, 256 tokens) over a 55-document, 7-class KB;
  - RRF fusion (k = 60, top 10) and a fitted 5-feature logistic reranker per class.
- **Union in `app.py`:** hybrid hits only add threats, and challenge-band hits are capped at weight
  0.5.
- **Eval:** 5,770 rows from PayloadsAllTheThings, codesagar and CHIMERA benign payloads, split 40%
  dev / 60% test. The reranker and thresholds are fitted on dev only.

Test split (1,899 attack / 1,514 benign):

| Variant | Attack hit recall | Benign false-hit | Attack escalated | Benign escalated | Retrieval p50 / p95 ms |
|---|---|---|---|---|---|
| regex only (previous) | 0.159 | 0.0086 | 0.171 | 0.0086 | 0.041 / 0.609 |
| **deployed union: regex + hybrid bge int8** | **0.6045** | 0.0159 | **0.627** | 0.0159 | 2.89 / 10.81 (hybrid) |

- **Live check:** `/health` reported `rag_hybrid_loaded: true` and `rag_dense_backend:
  bge_small_onnx_int8`. HTTP triage latency was p50 3.93 / p95 12.24 ms over 400 requests. This was
  a console run documented in MODEL_BENCHMARKS.md §4.1; no raw log file was kept.
- **Not measured:** recall for T1110, T1071, CB-CPN and CB-TL, which have no labelled text.
- **Weak spots:** short SQL fragments and shell one-liners (`1 AND SLEEP(5)`, `&& whoami`); the
  union hit rate on event-handler XSS is 0.0.
- **CI runs regex-only:** the encoder is a gitignored 34 MB artifact, so 22 tests pass and 5 skip.
- **Open product decision:** `CHALLENGE_WEIGHT` 0.45 would send 24% of attacks to `step_up`, which
  has no human review, instead of `constrain`. It is kept at 0.5.
- Sources: `ai-brain/benchmarks/rag/rag_benchmark.json`, `ai-brain/benchmarks/rag/triage_decisions.json`.

---

## 6. Card gate — observed fail-closed behavior (measured)

**Re-checked 2026-11-15 on the benchmark host** (in-process console check, documented in
MODEL_BENCHMARKS.md §1):
- `fraud-gate/artifacts/` is not empty here. It holds `creditcard_hgb.joblib`, a **synthetic toy**:
  version 1.0.0, `data_source synthetic_fallback_generator`, 30 features including `Time`,
  threshold 0.9192, and self-reported ROC/PR 1.0 on its own generator data.
- The simulator (`ScenarioCatalog.simulatedCardFeatures`) sends exactly 29 features (`V1`–`V28` =
  0.0, plus `Amount`); non-simulated orders send none. Both fail `INVALID_FEATURES`. The card
  component then scores 0.5 with `fallback=True`, and the policy returns **CHALLENGE on every
  order**.
- The real ULB artifact passes the same strict loader. It scores the simulator vector at
  0.000015 / 0.000021 / 0.000419 for amounts 25 / 120 / 999, all below its 0.0016 threshold.
- Promotion is an owner decision, because it changes CAPTURE outcomes:
  1. copy `fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib` to
     `fraud-gate/artifacts/creditcard_hgb.joblib`;
  2. run `docker compose restart fraud-gate fraud-gate-grpc`;
  3. check `/ready`.

  The CAPTURE saga has not been load-benchmarked with it.
- Wire (PaySim) is trained on synthetic data but has no runtime consumer. BAF still needs Kaggle
  credentials, which are absent.

**Earlier observation (dossier host; `fraud-gate/artifacts/` was empty at the time):**
- Live probe (containerized stack): `POST /orders` → CREATED;
  `POST /orders/{id}/authorize` → **STEP_UP, action=CHALLENGE, reasons=[GATE_TIMEOUT], captureId=null**.
- Under load the `fraudGate` circuit breaker went **OPEN**: failure_rate 100%, 40 failed calls,
  538 not_permitted short-circuits (`build-check/bench/metrics-final-idem.txt`).
- Consequence: **no CAPTURE settlement happened under load** — the capture saga is unit-tested only
  (3 tests), never load-exercised.

---

## 7. System benchmarks (measured, containerized, stub PayPal)

Environment: Docker VM 12 vCPU / 7.60 GiB bounds these, not the host. Full detail + sources:
`BENCHMARK.md`, raw files `build-check/bench/`.

| Metric | Measured |
|---|---|
| Max sustained RPS | read **48.11 req/s** (0% err); clean write **14.63 req/s**; write+1s-think **9.57 req/s** |
| Server latency | all-URI P95 **417.67 ms** / P99 709.23; create P95 542.18; authorize P95 697.29; cached read P95 9.75 |
| Concurrent transactions | 10 VUs → 578 create+authorize iterations / 1,157 requests in 2 min, 0% error |
| Duplicates prevented | **100/100**, 0% replay mismatch, 0% error (k6 + live curl, real Postgres) |
| Recovery (SIGKILL+start) | health UP **42.50 s**, functional **47.25 s** |
| Index speedups (300k rows, EXPLAIN ANALYZE median of 5) | owner_history 88.051→1.227 ms (**71.76×**); recent_feed 86.525→0.470 (**184.10×**); state_filter 80.228→50.001 (**1.60×**, low selectivity — reported honestly) |
| Cache hit ratio | **99.62%** (2,882/2,893), 30 s TTL cache-aside |
| Error rate under load | 0% ≤10 VUs; 6.38% @20 VUs; 70% @30 VUs (HikariCP pool starvation, fail-fast, clean recovery) |

Fixed bugs with before→after evidence:
- **Lock-ordering deadlock**: create_failed 82.76%→0%, P50 30,023→248.79 ms, throughput 0.25→9.57 req/s (~38×).
- **Idempotency created_at NOT-NULL 500**: every keyed POST was 500; fixed via `Persistable<String>`;
  verified live + k6 (100 duplicates prevented).

Honest limits: checkout write P95 530–644 ms **exceeds the 500 ms target** (global audit-chain
advisory lock serializes writes); **300 ms is a target budget, never achieved**; write ceiling
~14.6 req/s is profile-bounded, not a production capacity claim.

---

## 8. Test gates (measured)

| Suite | Result |
|---|---|
| defense-pipeline JUnit | 28 tests green (incl. 6 new `SemanticVerdictCacheTest`, one real-model repeated-text test) |
| platform-api JUnit | 56 tests green |
| Full gate `mvn -pl platform-api -am test` | see §10 gate log (this dossier's final run) |
| Adversarial battery (`AdversarialValidationTest`) | 200+ generated samples; asserts recall ≥0.95, precision ≥0.90, severity Pearson r ≥0.5 — **passes**; exact point values not recorded by the test |
| Evasion tests | homoglyph / nested-base64 / split-canary green |
| Testcontainers IT (4) | **SKIPPED on this Windows host** (docker-java cannot read the Desktop named pipe) — not executed against ephemeral Postgres |
| fraud-gate pytest | 59 passed, 1 skipped |
| ai-brain pytest | 13 passed |
| L4 JSON-vs-sklearn parity | max abs prob diff recorded in credit report; ONNX-vs-PyTorch decision parity 8/8 on error sample (max |Δp| 0.15) |

The table above is the dossier-host run. **Re-run 2026-11-15 on the benchmark host:** IntelliJ
2026.3 JBR (JDK 25) with its bundled Maven 3, plus `-Dnet.bytebuddy.experimental=true` for Mockito
on JDK 25; system Python 3.14.6.

| Suite | Result |
|---|---|
| defense-pipeline JUnit | 95 tests, 0 failures, 1 skipped |
| platform-api JUnit | 66/66, run in a scratch copy without the 7 untracked WIP test files (31 compile errors; §9) |
| Testcontainers IT (`EngineeringPersistenceIT`) | **4/4 pass** on `postgres:15-alpine` with `-Dapi.version=1.44`; Flyway applied V1→V3. Without the system property (default or environment-only), Docker 29.6.2 (API 1.55, minimum 1.44) answers HTTP 400 to Testcontainers 1.19.8 and all 4 skip |
| fraud-gate pytest | 60 passed, from a scratch venv (`build-check/fraud-gate-venv` points at another user's Python and does not start) |
| ai-brain pytest | 27 passed with the bge encoder present; without it, as in CI, 22 pass and 5 skip |

Logs:
- `build-check/mvn_test_2026-11-15_minus_wip_bb.log` (unit tests);
- `build-check/mvn_it_2026-11-15_api144.log` and `mvn_it_2026-11-15_sysprop_only.log` (4 pass);
- `build-check/mvn_it_2026-11-15.log` and `mvn_it_2026-11-15_envonly.log` (4 skipped).

The pytest runs were console runs; no log file was kept.

---

## 9. Known gaps (for the frontier-model gap analysis)

1. **Card gate trained but not promoted** (updated 2026-11-15). The real ULB model exists (recall
   0.827 [0.70–0.91] at FPR 0.0076; the XGBoost rival has higher ROC/PR AUC, MODEL_BENCHMARKS §1).
   The mounted artifact is a synthetic toy whose feature contract the simulator does not match, so
   every order still fails closed to CHALLENGE (§6). Promotion is the owner's decision.
2. **External generalization is weak**: spml_native recall 16.7% @0.65 (v4), 10.6% calibrated;
   FPR 6.8–9.9% vs 0.5% in-domain target. In-domain 91.1% is an upper bound (origin-style leakage).
   Under the locked v5 protocol (MODEL_BENCHMARKS §3), the distilled v6 reaches external recall
   0.588 at FPR 0.0235 and SPML-native recall 0.409, against 0.883 / 0.827 for the 184M ProtectAI
   rival. G1 (native ≥ 0.50 at FPR ≤ 2%) is still not met, and v6's test FPR misses the 0.02 budget.
3. **128-token window** explains 54.3% of external misses (injection buried past the window).
   Fixes: sliding-window max-pooling inference, longer-window base, or preamble-stripping — none implemented.
4. **English-only tokenizer**: German injections missed by design; needs multilingual base <100M params
   or translated `--extra` rows.
5. **Persona-jailbreak skill gap**: ~46% of external misses are inside the window but undetected;
   codesagar training data underrepresents this family.
6. **No severity calibration on real data** (0 severity labels in codesagar); Pearson r only on the
   synthetic adversarial battery.
7. **Credit metrics are synthetic-only**; no real credit-application data was used or claimed.
8. **Wire/BAF models** (updated 2026-11-15): the PaySim wire model is trained, but on simulator data
   (≈1.0 AUC is a simulator property, not skill) and with no runtime consumer; `retrain_v4.py` still
   skips the wire step. BAF has no trainer and needs Kaggle credentials.
9. **LoRA verdict model + Safe-LCB policy**: tooling only, never run; debate is a deterministic stub
   (±0.05 informational cap, never moves pre-capture scores).
10. **Retrieval evaluation uses mapped L4 labels**, not analyst-confirmed fraud cases.
11. **Write-path P95 above target**; audit-chain lock not sharded; no real PayPal/sandbox HTTP, no
    Render/hosted/browser verification, no production claim. Testcontainers ITs now pass with
    `-Dapi.version=1.44` (§8). CI is unchanged; the recommended fix is to pass that property in the
    integration job, or to upgrade Testcontainers.
12. **7 untracked WIP platform-api tests** do not compile against the current APIs (31 errors):
    `auth/RegistrationControllerTest`, `auth/WithMockChimeraUser`,
    `auth/WithMockChimeraUserSecurityContextFactory`, `banking/BankServiceTest`,
    `banking/MarketQuoteServiceTest`, `evaluation/ThreatSimulationServiceTest`,
    `outbox/KafkaOutboxPublisherTest`. Update or remove them (owner decision).
13. **Triage RAG gaps** (§5.2): no labelled text exists for T1110, T1071, CB-CPN or CB-TL, so their
    recall is unmeasured. Short SQL and shell fragments still slip through. `CHALLENGE_WEIGHT` 0.45
    is an open product decision.
14. **Case-memory retrieval** (§5): the fine-tune and hashed runs have no result, neural latency is
    5.9–9.2 s per query, and the labelled relevance benchmark (G4) is not run.
15. **Nothing from this work is committed.**
    - The new ai-brain code and models (`credit_brain.py`, `rag_engine.py`, `models/*.json`,
      `tests/`, `training/`) and the new docs are untracked, so CI sees none of it until committed.
    - `ai-brain/models/bge_small/` is gitignored by design.
    - The datasets (`datasets/new_custom_datasets/`, `new_datasets_v2/`, `new_datset_generator_v3/`,
      `synthetic_credit_boost/`) and the L4 artifact directories are untracked and not ignored.
      Ignoring them or moving them to Git LFS is the owner's decision.
16. **Genuine datasets still missing** are listed in MODEL_BENCHMARKS §9.1: gated Hugging Face sets,
    BAF and IBM AMLworld (Kaggle credentials), real credit-boost applications, labelled text for 4
    triage classes, L5/L6 recordings, and others.

---

## 10. Number → source map

| Claim | File |
|---|---|
| L4 test-split v1/v4 + calibrated | `build-check/v4-evals/score_{v1,v4}_{test065,testcal}.txt`, `java_*.log` |
| Cache replay | `build-check/v4-evals/java_{v1,v4}_test065.log` (`[L4 eval] replay` lines) |
| Semantic-only per-source | `build-check/v4-evals/probs_{v1,v4}_test.json` |
| External SPML overall/per-source | `build-check/v4-evals/pred_{v1,v4}_external.csv`, `pred_v4_externalcal.csv` + `external_breakdown.py` |
| External per-degree | `build-check/v4-evals/spml_degrees_v1_v4.txt`, `spml_degrees_v4cal.txt` |
| Token-window analysis | `l4_v4_external.jsonl` + `pred_v4_external.csv` (tokenizer count, §3.2) |
| v4 data manifest | `datasets/new_custom_datasets/out/v4/MANIFEST_V4.json` |
| Model metadata | `fraud-gate/training/artifacts/l4_semantic_guard{,_v4}/metadata.json` |
| Credit v1 / v2 | `datasets/synthetic_credit_boost/TRAINING_REPORT.json`, `build-check/v4-retrain/credit_v2_report.json` |
| Retrieval (case memory) | `build-check/v4-retrain/retrieval_neural_base.json` — the only retrieval result; no `retrieval_hashed.json`, `retrieval_neural.json` or `bge-small-chimera/` was produced (§5) |
| System benchmarks | `BENCHMARK.md`, `build-check/bench/*.json|txt` |
| Rules-only baseline, v1 history | `datasets/new_custom_datasets/EVALUATION.md` |
| Dataset/format/layer guide + retrain commands | `fraud-gate/training/README_V4.md` |
| Rival benchmarks, provenance and CIs (benchmark host) | `MODEL_BENCHMARKS.md` |
| Card, wire and L4 (v1/v4/v5, ProtectAI, TF-IDF) benchmarks | `fraud-gate/training/benchmarks/{card,wire,l4}/*_benchmark.{json,md}` |
| L4 v6 benchmark | `build-check/l4_distill/bench_v6/l4_benchmark.{json,md}` |
| Credit v3 | `ai-brain/benchmarks/credit_v3/credit_v3_benchmark.{json,md}` |
| Triage hybrid RAG (§5.2) | `ai-brain/benchmarks/rag/rag_benchmark.json`, `triage_decisions.json`, `rag_reranker_*.json` |
| 2026-11-15 test gates (§8) | `build-check/mvn_test_2026-11-15_minus_wip_bb.log`, `build-check/mvn_it_2026-11-15*.log` |