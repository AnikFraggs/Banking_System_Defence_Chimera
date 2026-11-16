# CHIMERA v4 retraining guide — datasets, formats, layers, scripts

Everything here is runnable. Numbers quoted as *measured* were produced on this host
(Windows 11, JDK 21, CPU-only Python 3.13 venv `build-check/fraud-gate-venv`); anything
else is explicitly marked as not run. No metric in this file is a target dressed up as
a result.

## 1. Which dataset trains which layer, in which format

| # | Layer / component | Dataset (source, licence) | Exact input format | Script | Status here |
|---|---|---|---|---|---|
| 1 | L4 semantic guard (prompt-injection ONNX) | `codesagar/malicious-llm-prompts-v3` (HF; licence not stated on the page — confirm before redistributing) via `chimera_datasets build` | `out/v4/l4_v4_train.jsonl`: `{"text": str<=2000, "label": 0|1, "repeat": 1..5 (optional), "source": str (optional)}` | `prepare_l4_v4_data.py` → `train_l4_semantic_guard.py` | **trained v4, measured** |
| 2 | L4 external held-out (never trained) | `reshabhs/SPML_Chatbot_Prompt_Injection` (HF, MIT) | raw `{"User Prompt", "Prompt injection", "Degree", "Source"}` → `out/v4/l4_v4_external.jsonl` `{"id","payload","label","source","degree"}` | `prepare_l4_v4_data.py --spml` | **fetched, measured** |
| 3 | L4 hard negatives / extra languages | your own licensed rows (e.g. translated deepset-style injections, roleplay jailbreaks, benign finance chat) | JSONL `{"text","label","source"}` passed with `--extra` (train-only, deduped against test/calib/external) | `prepare_l4_v4_data.py --extra` | script ready, no extra rows authored here |
| 4 | L4 deterministic rules (SQLi/XSS payloads) | `YangYang-Research/web-attack-detection` (HF, MIT) | CSV via `chimera_datasets build`; **evaluates rules, does not train a model** | `L4RealDataEvaluation` + `chimera_datasets score` | not fetched (625k rows) |
| 5 | Fraud-gate **card** model | ULB `creditcardfraud` via HF mirror `David-Egea/Creditcard-fraud-detection` (mirror MIT-tagged; original DbCL 1.0 — review) | `creditcard.csv` with `Time,V1..V28,Amount,Class` (284,807 rows, downloaded) | trainer `train_creditcard_hgb.py`; the measured artifact was emitted by `bench_card_fraud.py --emit-artifact fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib` (version `creditcard-hgb-ulb-v1`) | **TRAINED 2026-11-14, NOT PROMOTED** (real ULB, temporal split, thr 0.001601; loads via strict contract). `fraud-gate/artifacts/` still holds the synthetic toy — MODEL_BENCHMARKS.md §1 |
| 6 | Fraud-gate **wire** (simulated only) | PaySim via HF mirror `theman10/paysim` (mirror MIT-tagged; original CC BY-SA 4.0) | PaySim CSV `step,type,amount,...,isFraud` (6,362,620 rows, downloaded) | `train_paysim_wire.py` / `bench_wire_fraud.py` | **TRAINED 2026-11-14** (synthetic; ~1.0 AUC is a simulator property, not skill — MODEL_BENCHMARKS.md) |
| 7 | Fraud-gate **account opening** | Kaggle `sgpjesus/bank-account-fraud-dataset-neurips-2022` | `Base.csv` (`month`, `fraud_bool`, …) — catalogued, no trainer wired | none | not trained |
| 8 | RAG retriever (case memory bi-encoder) | train-split pairs (this repo) or your analyst-verdict pairs | JSONL `{"scenario_id","anchor","positive"}` (strings or telemetry objects) | `build_retrieval_pairs.py` → `train_contrastive.py` | see §4 |
| 9 | RAG retrieval evaluation | text_train corpus + text_test queries + real Redis | same splits; Redis via `docker run -d --rm -p 6399:6379 redis:7-alpine` | `evaluate_case_retrieval.py` | see §4 |
| 10 | Verdict LLM (LoRA) | analyst verdicts you are licensed to use | JSONL verdict records (see `train_lora_verdicts.py --prepare-only`) | `train_lora_verdicts.py` | tooling unit-tested, not run |
| 11 | Safe-LCB policy | train + held-out verdict JSONL | see `train_safe_lcb.py` | `train_safe_lcb.py --min-fraud-recall-lcb 0.8 --max-benign-friction 0.2` | tooling unit-tested, not run |
| 12 | AI-brain **credit** scorer | `datasets/synthetic_credit_boost/` (self-generated, synthetic) | `credit_apps.csv` + `credit_apps_adaptive.csv` (feature columns in `ai-brain/credit_brain.py`) | v2: `train_credit_brain.py --version credit-brain-lr-v2 --adaptive-train-frac 0.5`; v3 (default since 2026-11-15): `ai-brain/training/train_credit_brain_v3.py` | see §5 and MODEL_BENCHMARKS.md §4.2 |

Model IDs actually used (no invented IDs):
- L4 guard base: local `build-check/l4_base` (bert-mini-class WordPiece encoder, 11.17M params, English uncased vocab — German injections remain a known weakness).
- RAG bi-encoder: `BAAI/bge-small-en-v1.5`; cross-encoder: `cross-encoder/ms-marco-MiniLM-L-6-v2` (both opt-in via `CASE_BI_ENCODER_MODEL` / `CASE_CROSS_ENCODER_MODEL`).

### 1b. v5 additions (downloaded + hashed, data prep verified; **L4 v5 fine-tuned 2026-11-14**)

Manifest: `datasets/new_custom_datasets/raw/V5_DOWNLOAD_MANIFEST.json` (sha256 + row counts).
v5 data prep: `prepare_l4_v5_data.py` → `out/v5/MANIFEST_V5.json` (9,612 unique train rows, all
leakage checks 0; locks a 3,179-row external calibration slice of SPML before training). Orchestrator:
`retrain_v5.py` (default `--max-length 256`). Design: [`V5_DESIGN.md`](../../V5_DESIGN.md);
problem: [`PROBLEM_STATEMENT.md`](../../PROBLEM_STATEMENT.md).

| Layer / component | Dataset (HF source, licence) | Format | Rows | Intended use |
|---|---|---|---|---|
| L4 v5 positives (persona jailbreaks) | `TrustAIRLab/in-the-wild-jailbreak-prompts` (MIT) | parquet `prompt`,`jailbreak` | 2,071 raw → 750 unique | train (×2), the SPML-native failure class |
| L4 v5 hard negatives | same, `regular_*` | parquet | 19,456 → 2,000 sampled | train benign contrast (capped) |
| L4 v5 hard pos/neg | `JailbreakBench/JBB-Behaviors` (MIT) | CSV `Goal`,`Category` | 100 harmful + 100 benign | train (×2), same-topic pos/neg |
| L4 v5 external calib/test | `reshabhs/SPML…` (MIT, already fetched) | JSONL | 3,179 calib / 12,734 test | threshold calibration vs honest test |
| Card gate | `David-Egea/Creditcard-fraud-detection` (MIT mirror; orig DbCL) | CSV ULB schema | 284,807 | `train_creditcard_hgb.py` |
| Wire (simulated) | `theman10/paysim` (MIT mirror; orig CC BY-SA) | CSV PaySim schema | 6,362,620 | trained 2026-11-14 via `bench_wire_fraud.py` (row 6) |
| Account opening (BAF) | Kaggle `sgpjesus/bank-account-fraud…` | `Base.csv` | — | **no HF mirror; needs Kaggle creds (absent)** |

## 2. One-shot retrain

```bash
PY=build-check/fraud-gate-venv/Scripts/python.exe
$PY fraud-gate/training/retrain_v4.py --authorized-data \
    --neural-retrieval --redis-url redis://localhost:6399/0
# optional: --finetune-retriever (CPU fine-tune of bge-small on train-split pairs)
```

Every step is skipped with a recorded reason when its inputs are absent
(`build-check/v4-retrain/MANIFEST.json`). The card step needs the Kaggle CSV. `retrain_v4.py`
still skips the wire step ("no wire-schema trainer"); the PaySim trainer now exists, so run
`bench_wire_fraud.py` directly (§1 row 6, MODEL_BENCHMARKS.md §8).

## 3. L4 semantic guard v4 — what changed and what was measured

Data changes (`prepare_l4_v4_data.py`, manifest `out/v4/MANIFEST_V4.json`):
- v1 dropped 713 train rows > 2000 chars (incl. 188 malicious `jackhhao` roleplay rows);
  v4 truncates to 2000 chars instead (the model only reads 128 WordPiece tokens).
- Weak sources oversampled (`repeat` 2: deepset both labels, jackhhao-malicious, synthetic);
  repeats are expanded **after** the grouped split so held-out stays clean.
- Half of `text_dev` is mined with the v1 model: its 20 errors (14 FN / 6 FP) are added
  to train at `repeat` 3. The other dev half (650 rows) is reserved for threshold
  calibration only. Zero exact-normalized overlap between train and test/calib/external.
- SPML external held-out: 15,913 rows after dedup (98 overlapped existing splits).
  `spml_gandalf` (4,168) shares origin with training gandalf; `spml_native` (11,745) is
  the genuinely unseen distribution — reported separately.

Artifacts: `fraud-gate/training/artifacts/l4_semantic_guard_v4/`
(`model.int8.onnx` 11.37 MB int8, `metadata.json`: train 6,248 rows / 5,370 unique,
held-out 1,397, eval_loss 0.0489 vs v1 0.0612 — different internal splits, so the
test-split numbers below are the comparison that counts).

### End-to-end test split (1,257 rows, deterministic rules + guard, Java harness)

| Metric | v1 @0.65 | **v4 @0.65** |
|---|---|---|
| TP / FP / TN / FN | 227 / 10 / 989 / 31 | **235 / 6 / 993 / 23** |
| Recall | 88.0% | **91.1%** |
| FPR | 1.00% | **0.60%** |
| Precision | 95.8% | **97.5%** |

(Full Wilson CIs and per-source errors: `build-check/v4-evals/`, EVALUATION.md.)

### External held-out SPML (15,913 rows, never trained; end-to-end rules + guard)

| Config | Recall ALL | FPR | gandalf recall (origin-familiar) | native recall (true external) | native FPR |
|---|---|---|---|---|---|
| v1 @0.65 | 28.4% | 4.7% | 74.0% | 5.8% | 4.7% |
| **v4 @0.65** | **40.0%** | 9.9% | **86.9%** | **16.7%** | 9.9% |
| v4 @calibrated 0.9642 | 34.1% | 6.8% | 81.2% | 10.6% | 6.8% |

Honest reading: v4 improves external recall at every operating point but FPR rises too; the
in-domain calibrated threshold does **not** transfer (6.8% external FPR vs 0.5% dev target).
Per-degree recall degrades with obfuscation: native degree 7/10 is worst (v4 10.7%/9.4% @0.65).
54.3% of missed native attacks exceed the 128-token model window (injection buried after a long
persona preamble); the rest are in-window skill gaps. Full tables, CIs and failure analysis:
`RESULTS_DOSSIER.md` §3, `build-check/v4-evals/spml_degrees_*.txt`.

### Verdict cache (protection unchanged, latency improved)

`SemanticVerdictCache`: bounded LRU (default 4,096, `L4_SEMANTIC_CACHE_SIZE`, 0 disables),
keyed by SHA-256 of the exact payload; raw text is never stored; timeouts/errors are never
cached. Measured on the same 1,257-row replay pass (single thread, same host):

| | v1 first pass | v1 replay (cached) | v4 first pass | v4 replay (cached) |
|---|---|---|---|---|
| p50 per payload | 45 ms | **0.98 ms** | 33 ms | **0.45 ms** |
| p95 | 95 ms | 10.1 ms | 80 ms | 3.9 ms |
| decision mismatches | — | **0 / 1,257** | — | **0 / 1,257** |

Cache hits: 1,256/1,256 eligible payloads (one payload is blank and short-circuits).
The cache only helps repeated/replayed payloads; first-seen payloads pay full inference.

## 4. RAG / case-memory improvements

1. **Candidate generation**: `RedisCaseMemory.match()` used to load only the first 128
   archetype ids — everything else was invisible. v4 adds deterministic LSH buckets
   (12 bands × 8 sign bits over the 128-dim hashed vectors) and ranks candidates by
   bucket collisions; `candidate_strategy="first_page"` reproduces the old behavior,
   `rebuild_buckets()` backfills old archetypes.
2. **Embedding cache**: the neural matcher re-encoded all 128 candidate texts on every
   query. v4 caches candidate embeddings by SHA-256(text) (bounded LRU,
   `CASE_EMBEDDING_CACHE_SIZE`, default 4096).
3. **Rerank window**: the cross-encoder now scores only the bi-encoder top
   `CASE_RERANK_TOP_K` (default 20) instead of all 128 candidates.
4. **Triage KB**: two new entries (`CB-CPN`, `CB-TL`) cover credit-boost typologies.

Measured with `evaluate_case_retrieval.py` (real Redis 7, 6,146-archetype corpus from
text_train, 200 text_test queries, seed 13). **Neural base models** (bge-small-en-v1.5 +
ms-marco-MiniLM-L-6-v2, as-is), source `build-check/v4-retrain/retrieval_neural_base.json`:

| Scenario | recall@5 vs top-10 | verdict precision@5 | majority-vote acc | p50 / p95 latency |
|---|---|---|---|---|
| full_corpus | 0.036 ⚠ invalid | 0.036 | 0.885 | 5,858 / 15,820 ms |
| legacy_page (first_page) | 0.04 | 0.04 | 0.83 | 7,161 / 18,353 ms |
| lsh_buckets | **0.12** | 0.12 | 0.875 | 9,184 / 16,624 ms |

**⚠ full_corpus is a benchmark artifact, not model quality.** `case_matching.py` caps candidates at
`MAX_CANDIDATES=128` and truncates **by list position**; the harness feeds all 6,146 in corpus order,
so the matcher only sees rows 0–127 while ground truth spans all 6,146. Expected-by-chance recall
≈ 10×(128/6146)/5 ≈ 0.042 ≈ the measured 0.036. The valid comparison is **lsh 0.12 vs legacy 0.04**
(a real 3× gain from LSH candidate generation, both far below the brute-force ceiling). Embedding
cache worked (8,192 ≥ corpus: 77,184 hits / 6,146 misses). **Latency p50 5.9–9.2 s/query is the
headline problem** (torch thread oversubscription + cross-encoder on 20 long pairs); neural path is
opt-in / async-only. The hashed and fine-tuned-bi-encoder runs have **no recorded result** (checked
2026-11-15): the fine-tune log stops after model load, and no `retrieval_hashed.json`,
`retrieval_neural.json` or `bge-small-chimera/` output exists. See RESULTS_DOSSIER.md §5 and
PROBLEM_STATEMENT.md P4/P5 for the v5 fix plan. The separate ai-brain triage RAG (hybrid BM25 + bge
ONNX int8) is deployed and measured in MODEL_BENCHMARKS.md §5.1.

## 5. Credit brain v2 (measured, synthetic data only)

`train_credit_brain.py --adaptive-train-frac 0.5` adds a ring-grouped half of the
adaptive-seller set to training (28,067 train rows); the other half (4,920 rows,
298 fraud) is an untouched holdout, and v1 is scored on the same holdout
(`--compare-model`). A ring never straddles train/holdout.

| Metric (adaptive holdout) | v1 | **v2** |
|---|---|---|
| ROC-AUC / PR-AUC | 0.9457 / 0.8697 | **0.9535 / 0.9189** |
| Recall (any action) | 84.6% | **89.6%** |
| FPR (any action, legit applicants) | 3.29% | **1.69%** |
| `fraud_tradeline_boost` approved | 25.3% | **10.7%** |
| `fraud_approval_package` approved | 4.0% | **0.0%** |
| `fraud_cpn_synthetic` approved | 5.1% | **0.0%** |
| `legit_improver` approved | 93.6% | **96.1%** |

Main test split: recall unchanged (95.2%), FPR 3.74% → **1.99%**. v2 became the default
(`ai-brain/models/credit_brain_v2.json`); v1 stays for comparison. Full report:
`build-check/v4-retrain/credit_v2_report.json`. These numbers show recovery of the
synthetic generator's signal, **not** real-world credit-fraud quality.

**Superseded 2026-11-15:** v3 (LightGBM, `ai-brain/models/credit_brain_v3.json`) is now the
default. v2 stays available for rollback via `CREDIT_BRAIN_MODEL_PATH`. The comparison, also on
synthetic data only, is in MODEL_BENCHMARKS.md §4.2.

## 6. What is still NOT done (honest list)

- Card and wire models are trained (§1 rows 5–6) but **not promoted**. The card gate still fails
  closed to CHALLENGE, because `fraud-gate/artifacts/` holds the synthetic toy (MODEL_BENCHMARKS.md
  §1). Account opening (BAF) still needs Kaggle credentials.
- The L4 guard's English-only tokenizer still misses German-language injections;
  fixing that needs a multilingual WordPiece base < 100M params or translated `--extra` rows.
- `spml_gandalf` external results are origin-familiar; treat `spml_native` as the
  generalization number.
- Retrieval evaluation uses L4 labels mapped to FRAUD/BENIGN verdicts on real payload
  text — it measures the retrieval machinery, not analyst-confirmed fraud similarity.
- No production/deployment claim: everything above is in-process measurement.
