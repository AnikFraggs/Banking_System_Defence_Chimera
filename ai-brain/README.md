# CHIMERA AI Brain

FastAPI service (`app.py`) that the Java `platform-api` calls through `AiBrainClient`. It runs
fully offline and never calls an external LLM.

| Endpoint | What it is |
|---|---|
| `POST /v1/triage` | Cyber triage. Regex signatures over 7 attack classes, escalated by a **hybrid RAG retriever** (`rag_engine.py`), feeding a hand-weighted logistic risk score. Only the retriever's reranker is fitted; the risk formula is not trained. Java uses it escalate-only: `AiBrainSeverityAdvisor` takes the max of the local severity and the brain's risk. |
| `POST /v1/credit-application/score` | Credit brain **v3**: 300 LightGBM trees traversed in pure Python, trained on a **synthetic** credit-boost dataset, plus an article-grounded red-flag knowledge base (`credit_brain.py`). |
| `GET /health` | `status`, `model`, `knowledge_entries`, `rag_hybrid_loaded`, `rag_dense_backend`, `credit_model_loaded`, `credit_model_version`. |

Java routes (`AiBrainController`, roles ACCOUNTANT / MANAGER): `GET /api/ai-brain/health`,
`POST /api/ai-brain/triage`, `POST /api/ai-brain/credit-application`.

## Triage: hybrid RAG

The query text is the telemetry's `payload`, `purpose`, `message`, `detail` and `text` fields.

1. **Regex signatures** per class (`KNOWLEDGE` in `app.py`), as before.
2. **Hybrid retriever** (`rag_engine.py`):
   - **Canonicalize:** NFKC, strip zero-width characters, up to 2 rounds of URL and HTML decoding.
     Redact emails to `<email>` and Luhn-valid 13–19-digit numbers to `<pan>`, then lowercase.
   - **Sparse:** BM25 (k1 1.2, b 0.75). The tokenizer keeps symbols such as `'`, `--`, `<`, `|`
     and `;` searchable.
   - **Dense:** BAAI/bge-small-en-v1.5 (MIT, ~33M params) as ONNX opset 17 with dynamic int8.
     CLS pooling, L2-normalised 384-d vectors, 256 tokens, onnxruntime CPU with 4 threads.
   - **Fusion:** reciprocal rank fusion (k = 60) of the two rankings, top 10 documents.
   - **Reranker:** logistic model (`models/rag_reranker.json`) over 5 per-class features: dense
     max, log1p(BM25 max), RRF × 60, idf-weighted query coverage, regex hit.
   - **Bands:** probability ≥ 0.93346 is a challenge hit; ≥ 0.96779 is a block hit.
3. **Union, escalate-only:** a regex or block-band hit counts at the class weight. A challenge-band
   hit counts at min(weight, `CHALLENGE_WEIGHT` = 0.5). Hybrid hits never remove a regex hit.
4. **Risk** = logistic(2.4 · max weight + 1.6 · `behavior_anomaly` + 1.5 · [invalid workload identity] − 1.2).

| Risk | Recommendation | Human approval |
|---|---|---|
| ≥ 0.75, or invalid workload identity | `isolate_session` | yes |
| ≥ 0.5 | `constrain` | yes |
| ≥ 0.3 | `step_up` | no |
| below 0.3 | `allow` | no |

Payload-only telemetry tops out at 0.7465 (weight 0.95), so isolation needs behavioural anomaly or
an invalid workload identity.

**Knowledge base:** 7 classes, 55 documents. Each class contributes its name + mitigation and the
curated docs below.

| Class | Weight | Regex patterns | Curated docs |
|---|---|---|---|
| T1190 SQL Injection | 0.95 | 4 | 10 |
| T1059 Command / Script Injection | 0.9 | 4 | 10 |
| T1566 Prompt Injection / Social Engineering | 0.85 | 4 | 10 |
| T1110 Brute Force / Credential Stuffing | 0.7 | 3 | 5 |
| T1071 Data Exfiltration | 0.8 | 4 | 5 |
| CB-CPN Synthetic Identity / CPN Credit File | 0.9 | 5 | 4 |
| CB-TL Tradeline Boosting / Approval Package | 0.8 | 6 | 4 |

**Fail-safe, no fallback encoder.** The reranker is fitted for the bge int8 encoder. If
`models/bge_small/model_int8.onnx` or `models/rag_reranker.json` is missing, the hybrid is
disabled and triage is regex-only; `/health` then shows `rag_hybrid_loaded: false` and
`rag_dense_backend: null`. The encoder is a gitignored 34 MB artifact, so CI runs regex-only.
Re-create it with `training/export_bge_onnx.py`.

No LLM consumes the retrieved text, so there is no instruction-stripping stage. Adding an LLM
consumer would require one.

## Credit brain policy

- Decisions: `approve_standard_checks`, `step_up_verification`, `manual_review`. **Never
  auto-declines**; adverse action stays with a human.
- Hard identity flags (linked to another identity, eCBSV no-match, death record) always go to
  manual review.
- Missing model file, unreachable brain, or brain 5xx: **fail closed to manual review** (Python
  and Java).
- Input is derived evidence only. Unknown fields (e.g. `ssn`) are rejected with 422, and Java
  returns a generic 400 without echoing input.
- Step-up recommends the consent-based eCBSV check only where risk justifies its per-check cost.
- Model selection: `CreditBrain.load(path)`, else `CREDIT_BRAIN_MODEL_PATH`, else
  `models/credit_brain_v3.json`. v1 and v2 (logistic regressions) still load for rollback, e.g.
  `CREDIT_BRAIN_MODEL_PATH=models/credit_brain_v2.json`.
- Reason codes: Saabas path attribution on the v3 trees (sums exactly to the logit); v1/v2 use
  coefficient × standardized value.

Typologies modelled (source: Resistant AI, "Credit boost fraud: buying your way into a better
credit score"): purchased authorized-user tradelines, credit sweeps, CPN synthetic identities sold
with a 700-750+ score, and seller-run approval packages (CPN + tradelines + fake pay stubs, one
operator device for many buyers). Hard negatives: family AU piggybacking, newcomers with a recently
issued SSN, rebuilders filing accurate disputes, genuine score improvers.

## Models

| File | Version | Notes |
|---|---|---|
| `models/credit_brain_v3.json` | `credit-brain-lgbm-v3` | **Default.** 300 trees, 665,786 bytes, parity with `lightgbm.predict_proba` max \|Δp\| 0.0. |
| `models/credit_brain_v2.json` | `credit-brain-lr-v2` | Rollback. LR trained with half of the adaptive seller rings. |
| `models/credit_brain_v1.json` | `credit-brain-lr-v1` | Rollback. LR on the main split only. |
| `models/rag_reranker.json` | `dense: bge_small_onnx_int8` | Reranker weights and band thresholds. |
| `models/bge_small/` | bge-small-en-v1.5 int8 | `model_int8.onnx` (33,972,472 bytes) + `tokenizer.json`. **Gitignored.** |

Serving needs only `requirements.txt` (fastapi, uvicorn, pydantic, numpy, onnxruntime,
tokenizers). LightGBM, scikit-learn and torch are training-time only.

## Data

- **Credit:** `datasets/synthetic_credit_boost/`. 40,000 rows (7% fraud, ring-grouped 60/20/20
  split by `sha256(ring_id)`, 0 rings straddle splits) plus a 10,000-row **adaptive-seller** shift
  set (aged CPNs, staggered AU purchases, rotated devices, better documents). 0.4% label noise. No
  SSN/CPN, name or account strings are generated (checked: 0 matches for `\d{3}-\d{2}-\d{4}` or
  bare 9-digit numbers).
  - v2/v3 splits: train 28,067 / val 8,985 / test 8,028 (651 fraud) / ring-grouped adaptive
    holdout 4,920 (298 fraud). v3's trainer refuses to run if they differ from v2's.
  - v3 stress sets: an unseen generator seed (777001), 10,000 rows, 748 fraud. `stress_fresh_rings`
    has unseen adaptive seller rings. `stress_stealth_graft` copies 3–6 attacker-controllable
    fields from a random legit row into each fraud row.
- **Triage RAG eval:** `datasets/new_custom_datasets/out/rag_eval/` (5,770 rows after dropping 825
  duplicates; sha256 `11f8ee29…4d97e8c`).
  - T1190 and T1059: PayloadsAllTheThings Intruder lists (MIT, pinned commit `08ea40e7`).
  - T1566: malicious rows of codesagar/malicious-llm-prompts-v3 (licence not stated), which
    aggregates Lakera gandalf, jackhhao jailbreak and deepset/prompt-injections.
  - Benign: the same corpora's benign rows plus the CHIMERA layer CSVs' unique benign payloads.
  - Split by a stable text hash: 40% dev / 60% test. Test has 1,899 attacks and 1,514 benign.
  - **No labelled text exists for T1110, T1071, CB-CPN or CB-TL**, so their recall is unmeasured.

## Measured results

Environment: Windows 11 (10.0.26200), Python 3.14.6, onnxruntime 1.31.1, LightGBM 4.7.0, torch
2.13.0+cpu (export and fp32 comparison only). Full tables: `MODEL_BENCHMARKS.md` §4.2 and §5.1.

### Triage RAG (test split; thresholds set on dev only)

| Variant | Attack hit recall | Benign false-hit | Attack escalated | Benign escalated |
|---|---|---|---|---|
| regex only (previous) | 0.159 | **0.0086** | 0.171 | **0.0086** |
| **deployed: regex + hybrid bge int8** | **0.6045** | 0.0159 | **0.627** | 0.0159 |

- **3.7× more attacks escalated** (0.171 → 0.627). The cost is 11 more of 1,514 benign queries.
- Retriever latency per query, including encoding: p50 2.89 / p95 10.81 / max 13.57 ms. The int8
  encoder matches torch fp32 in quality (headline recall 0.687 vs 0.681) and is ~4× faster.
- What drives the gain: the dense encoder (hashed char n-grams reach 0.416, bge 0.687) and the
  curated docs (name + mitigation only collapses to 0.171).
- Weak spots: short SQL fragments and shell one-liners, e.g. `1 AND SLEEP(5)`,
  `<body onload=...>`, `| cat /etc/passwd`, `&& whoami`.
- Policy option, **not applied**: `CHALLENGE_WEIGHT` 0.45 would send 24% of attacks to `step_up`
  (no human review) instead of `constrain`. The escalation rate is unchanged.

### Credit brain v3 vs v2 (synthetic data only)

End-to-end decisions through `CreditBrain.assess`, hard flags included.

| Set | Model | PR-AUC | Recall (any action) | FPR (any action) | FPR (manual review) |
|---|---|---|---|---|---|
| test | v2 LR | 0.9576 | 0.952 | 0.0199 | **0.0133** |
| test | **v3** | 0.9575 | 0.952 | **0.0184** | 0.0159 |
| adaptive holdout | v2 LR | 0.9189 | 0.896 | 0.0169 | **0.0121** |
| adaptive holdout | **v3** | **0.9369** | **0.926** | **0.0151** | 0.0123 |
| stress fresh rings | v2 LR | 0.9318 | 0.902 | 0.0191 | **0.0120** |
| stress fresh rings | **v3** | **0.9421** | **0.931** | **0.0165** | 0.0142 |
| stress stealth graft | v2 LR | 0.9262 | 0.894 | 0.0191 | **0.0120** |
| stress stealth graft | **v3** | **0.9420** | **0.931** | **0.0165** | 0.0142 |

- v3 raises recall and lowers any-action FPR together on the shifted sets, so it was adopted.
- Trade-off: slightly more legit applicants go to manual review (test 0.0159 vs 0.0133).
- Thresholds were chosen on val (val FPR 0.005, recall 0.95): t_low 0.010413, t_high 0.014313.
- `assess` latency: v3 p50 0.20 / p99 0.39 ms; v2 p50 0.011 ms.
- The v1 baseline (Python 3.13.15, scikit-learn 1.6.1) had test ROC-AUC 0.976 / PR-AUC 0.960 and
  approved adaptive tradeline boosting 23.6% of the time. v2 and v3 were trained to close that.

**Caveat:** the same generator wrote the training and evaluation data, and the in-distribution
test set is close to separable by construction. These numbers show the model recovers the
generator's signal. They are **not** evidence of real-world credit-fraud detection quality, which
would need labelled bureau/application data.

### Live check (2026-11-15, uvicorn on 127.0.0.1, 1 worker)

- `/health`: `rag_hybrid_loaded: true`, `rag_dense_backend: bge_small_onnx_int8`,
  `credit_model_version: credit-brain-lgbm-v3`, `knowledge_entries: 7`.
- Triage: UNION-SELECT injection 0.7465 → `constrain`; with `behavior_anomaly 0.4`, 0.8481 →
  `isolate_session`; a benign banking question 0.2315 → `allow`.
- Credit: prime applicant 0.0001 → `approve_standard_checks`; seller-run CPN package 0.9996 →
  `manual_review`, `auto_decline: false`.
- HTTP latency over 400 sequential requests: triage p50 3.93 / p95 12.24 ms, credit p50 0.80 /
  p95 1.18 ms.

## Reproduce

```bash
# Credit (synthetic)
python ai-brain/training/generate_credit_apps.py      # -> datasets/synthetic_credit_boost/
python ai-brain/training/train_credit_brain.py        # v1 -> models/credit_brain_v1.json + TRAINING_REPORT.json
python ai-brain/training/train_credit_brain.py --version credit-brain-lr-v2 --adaptive-train-frac 0.5 \
  --out ai-brain/models/credit_brain_v2.json --compare-model ai-brain/models/credit_brain_v1.json \
  --report build-check/v4-retrain/credit_v2_report.json
python ai-brain/training/train_credit_brain_v3.py     # v3 + v2-vs-v3 benchmark -> benchmarks/credit_v3/

# Triage hybrid RAG (export needs torch, transformers and onnx, from a local bge-small checkpoint)
python ai-brain/training/build_rag_eval.py --authorized-data
python ai-brain/training/export_bge_onnx.py           # build-check/students/bge_small -> models/bge_small/
python ai-brain/training/bench_rag.py --bge-onnx ai-brain/models/bge_small --bge build-check/students/bge_small
python ai-brain/training/bench_triage_decisions.py --what-if-challenge-weight 0.45
cp ai-brain/benchmarks/rag/rag_reranker_hybrid_bge_small_onnx_int8.json ai-brain/models/rag_reranker.json

# Tests
cd ai-brain && python -m pytest tests -q
```

## Tests and CI

- `tests/test_app.py`: 27 tests. With the encoder present all 27 pass. Without it, 22 pass and the
  5 paraphrase tests skip.
- `.github/workflows/ai-brain.yml` runs the tests on Python 3.12, an import smoke, and the Docker
  image build. CI has no encoder, so it covers the regex-only path.
- `models/credit_brain_v3.json` must be committed, or `test_model_artifact_is_loaded` fails.
  Commit `models/rag_reranker.json` too, or the hybrid stays off even where the encoder exists.
  Only `models/bge_small/` is gitignored.
- The `Dockerfile` copies `app.py`, `credit_brain.py`, `rag_engine.py` and `models/`. Images built
  without `models/bge_small/` serve regex-only triage.
