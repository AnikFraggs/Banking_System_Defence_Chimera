# CHIMERA v5 — Design Proposal (successor to v4)

**Status:** design + wired scripts. **Update 2026-11-14: v5 L4 is now fine-tuned (bert-mini, int8
ONNX) and the card/wire gates are trained on the real local datasets** — measured results, rival
benchmarks and goal-by-goal (G1–G7) status are in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md).
**G1 is NOT met** (external SPML recall ~16% vs the ≥50% goal); G5/G6 are closed. Data prep is executed and
verified (`datasets/new_custom_datasets/out/v5/MANIFEST_V5.json`, all leakage checks 0); downloads
are hashed (`raw/V5_DOWNLOAD_MANIFEST.json`). Every *goal* below is labelled as a goal — none is a
measured result. Measured v4 baselines are in `PROBLEM_STATEMENT.md` / `RESULTS_DOSSIER.md`.

**Read with:** `PROBLEM_STATEMENT.md` (the problem, P1–P10, with file:line evidence). This document
is the current team's proposed solution; a frontier model is expected to critique and improve it.

---

## 1. v5 objectives (goals, not results)

| # | Goal | Baseline (measured v4) |
|---|---|---|
| G1 | SPML-native recall ≥ 50% @ native FPR ≤ 2% (external-test slice) | 16.7% @ 9.9% (@0.65) |
| G2 | In-domain test recall ≥ 90% @ FPR ≤ 0.5% end-to-end | 91.1% @ 0.60% (@0.65); 88.4% @ 0.30% (@cal) |
| G3 | Long-payload coverage: attacks with >126 tokens no longer auto-missed | 54.3% of misses out-of-window |
| G4 | Neural retrieval p50 ≤ 100 ms/query on this CPU; valid benchmark | p50 5,858 ms; full_corpus scenario invalid |
| G5 | Card gate trained + CAPTURE path load-tested | untrained, fail-closed, breaker OPEN |
| G6 | Simulated-wire trainer exists and is measured | no trainer |
| G7 | Every claim traceable to an artifact; stale docs rewritten | README.md stale (P10) |

Hard constraints: PROBLEM_STATEMENT.md §2 (CPU-only, <100M params, WordPiece/ONNX int8, 250 ms
production timeout, escalate-only, fail-closed, stub PayPal, ±0.05 async LLM cap).

---

## 2. Track A — L4 v5 model (P1, P3, P8)

### 2.1 Data recipe (built and verified, not trained)

`fraud-gate/training/prepare_l4_v5_data.py` → `out/v5/` (manifest sha256-locked):

- v4 base kept: codesagar train + dev-mined half (mining will use the **v4** artifact on the real
  run), weak-source repeats, >2000-char truncation.
- **New positives:** JailbreakBench harmful behaviors (100, ×2) + TrustAIRLab in-the-wild
  jailbreaks (2,071 raw → **750 unique** after exact-normalized dedup across the two snapshots, ×2).
  These are the persona/roleplay class that SPML-native exposes (P1).
- **New hard negatives:** JBB benign behaviors (100, ×2 — same topics as the harmful set, benign
  framing) + in-the-wild regular prompts (19,456 available → **2,000 hash-sampled**, cap
  `--max-regular-benign`, seed-stable). Benign additions are capped so they don't swamp the mix.
- Result: **9,612 unique train rows / 11,630 after repeat** (v4: 5,370 / 6,248). Label conflicts
  dropped: 11. Eval-overlap rows blocked: 276.
- **External calibration lock (the P3 fix):** SPML external (15,913) is split by
  `sha256("v5-calib:"+id)[:8] % 5 == 0` into **3,179 calibration rows (19.98%)** and **12,734
  external-test rows**, stratified by construction across source×label (realized: gandalf 843/3,325;
  native benign 694/2,678; native malicious 1,642/6,731). The full file is kept for v4-comparable
  numbers. **The calib slice may tune thresholds; the test slice may only be scored once per
  candidate model, after selection.** No training row overlaps any eval slice (verified, 0/0/0/0/0).

### 2.2 Training

`retrain_v5.py --steps l4-train` wires `train_l4_semantic_guard.py` with:
- `--max-length 256` (default; the user's new flag; the stopped v4-candidate run proves the path
  exists but produced **no artifact** — 8/782 steps). v5 expanded rows → ~1,454 steps at batch 16 ×
  2 epochs; CPU-hours, run unattended. **Measure step time before committing to more epochs.**
- `--positive-weight` sweep {1, 2, 3} **on the in-domain calib slice only** (weighted CE already
  implemented by the user's `RecallWeightedTrainer`).
- `--calibration-data out/v5/l4_v5_calib.jsonl --max-calibration-fpr 0.005` for the in-domain
  operating point; **additionally** calibrate on `l4_v5_external_calib.jsonl` via
  `score_l4_onnx.py::choose_threshold` and report both operating points. Deploy decision rule:
  pick the threshold whose **worst-case FPR across both calib sets** ≤ budget; never pick on
  external-test.
- Base stays `build-check/l4_base` (11.17M params, English WordPiece) — constraint-compliant.

### 2.3 De-leakage and multilingual (P1 origin-style, P8)

- Source-balanced sampling already in the recipe; add **style augmentation** candidates for the
  frontier model to weigh: paraphrase/back-translation of gandalf-style rows, persona-template
  randomization, and source-adversarial (gradient-reversal) training. The last adds complexity —
  try the cheap ones first and measure per-source recall spread (gandalf vs deepset vs native).
- Multilingual under <100M + WordPiece: most multilingual encoders exceed 100M (DistilBERT-mbert
  134M, mMiniLM-L12 ~117M). **Constraint-compliant default: translate-to-English augmentation at
  prep time** (German deepset rows → English variants, both kept). A multilingual runtime is a
  bigger change (vocab + Java tokenizer) — only if augmentation measurably fails.

### 2.4 Shift-aware operating points (P3, industry practice)

- Two-slice calibration (in-domain + external-calib) as above.
- Optional **conformal p-value / quantile calibration** on the external-calib benign scores for a
  distribution-free FPR guarantee *on that distribution*; state the exchangeability caveat.
- Runtime **drift guard**: track a rolling histogram of guard probabilities (Redis, async); when
  the benign-side mass shifts (PSI > threshold), tighten the operating threshold or route to
  step-up. This is a v5+ stretch item — design only, not wired.

## 3. Track B — the 128-token window (P2, G3)

The binding defect: `WordPieceTokenizer.java:64` head-truncates; 54.3% of missed native attacks
live past token 126. Options, cheapest first:

1. **256-token retrain (Track A)** — doubles the window; still misses the tail of 1,000+ token
   persona preambles. Necessary but not sufficient.
2. **Chunked sliding-window max-pool in Java (no retrain):** split the payload into ≤256-token
   chunks with 32-token overlap, score each, take max probability. Latency arithmetic from
   *measured* v4 numbers (p50 22–33 ms per 128-token pass, single-thread int8): a 256-token pass
   costs more (measure it — do not assume linear); a 2,000-char payload ≈ 400–600 tokens ≈ 2–3
   chunks. If a 256-pass measures ~60–90 ms, 3 chunks ≈ 180–270 ms — **borderline against the
   250 ms budget**. Mitigations, in order: (a) verdict cache already absorbs repeats;
   (b) deterministic short-circuit already skips rule-blocked payloads; (c) **cascade**: run the
   fast single pass first; only payloads whose probability lands in a borderline band (e.g.
   0.2–0.65) or whose length exceeds the window pay for chunked deep-scan; (d) deep-scan async for
   the rest (step-up now, refine later — matches the existing L5 flow).
3. Head+tail sampling (first 128 + last 128 tokens) — cheap, catches buried-tail injections,
   misses middle; evaluate as a baseline against chunking.

**Decision gate:** measure per-pass latency at 256 on this CPU, then pick the cascade band from
the external-calib score distribution. Everything stays escalate-only and fail-closed.

## 4. Track C — retrieval (P4, P5, G4)

1. **Fix the benchmark first** (`evaluate_case_retrieval.py`): the full_corpus scenario must
   pre-rank candidates by bi-similarity and pass the top `MAX_CANDIDATES` (128) to `match()`, or
   report truncation explicitly. Positional truncation makes the current 0.036 meaningless
   (expected-by-chance ≈ 0.042). Keep legacy_page as the weak baseline; lsh_buckets is the real
   candidate-generation comparison.
2. **Latency:** pin `torch.set_num_threads` (≤ physical cores) in the eval and matcher startup,
   or export bge-small + cross-encoder to ONNX int8 (the L4 guard proves 10–33 ms p50 single-thread
   is achievable). The eval's embedding cache (8,192) already covered the corpus (77,184 hits /
   6,146 misses) — cache is not the bottleneck there; the **production default is 4,096**, below a
   6,146-case corpus, so size it to the corpus in deployment.
3. **Quality:** the fine-tuned bge-small (`train_contrastive.py`, 1,521 pairs, running now) is the
   first step; then recalibrate the blend weights (`case_matching.py:318-322`) on the fixed
   harness — the 0.10 weight on a single `payload_chars` feature and the out-of-domain MS-MARCO
   cross-encoder are suspects, **unverified until the harness is fixed**.
4. Production posture unchanged: neural matcher opt-in, async worker path; hashed matcher stays
   the synchronous default.

## 5. Track D — card gate (P6, G5) and wire (P7, G6)

**Card (data ready, trainer exists, never run):**
- `retrain_v5.py --steps card` → `train_creditcard_hgb.py` on `raw/creditcard_ulb/creditcard.csv`
  (284,807 rows; 492 fraud = 0.17%). Stratified split, PR-AUC + recall@fixed-FPR (not accuracy),
  cost-sensitive threshold aligned to `policy.py` bands (≥0.85 VOID, ≥0.35 CHALLENGE).
- Export the ONNX variant (`onnx_card_model.py`), mount in compose, then **re-run k6 checkout-load
  + saturation**: the CAPTURE settlement saga and breaker recovery become measurable for the first
  time (v4 load only exercised CREATED→STEP_UP).
- License caveat: HF mirror tagged MIT, original ULB DbCL 1.0 — review before redistribution.

**Wire (data ready, trainer missing):** write `train_paysim_wire.py` (frontier-model task):
per-account sequence aggregates over `step`, type-conditional amount distributions,
balance-delta consistency (`oldbalanceOrg − amount ≈ newbalanceOrig` violations), fan-in/fan-out
degree, velocity; HGB baseline; **simulated-wire typology only — never the card gate**. PaySim
6,362,620 rows; mirror MIT-tagged, original CC BY-SA 4.0. BAF: no HF mirror; needs Kaggle creds.

## 6. Track E — severity + documentation (P9, P10)

- Severity: no severity labels exist in any real dataset. Policy decision for v5: allow
  semantic BLOCK when probability ≥ a high calibrated quantile (e.g. 0.99 on both calib sets) —
  measure the false-BLOCK cost on external-calib benign first. Keep escalate-only invariant.
- Rewrite `README.md` "Where improvements are needed" from RESULTS_DOSSIER.md; fill README_V4 §4
  retrieval tables with the fixed-harness numbers; keep the NOT-done list honest.

## 7. Evaluation protocol (what v5 must measure before any claim)

1. Java end-to-end (`L4RealDataEvaluation`, `retrain_v5.py --java-eval`) on: in-domain test,
   external-test, external-full (v4-comparable). Report TP/FP/TN/FN + Wilson CIs, per-source and
   per-degree, decision mix, latency p50/p95/max vs the 250 ms budget.
2. Semantic-only scores (`score_l4_onnx.py`) for the same sets — separates model skill from rules.
3. Both operating points (in-domain-calibrated, external-calibrated) — never a threshold picked on
   external-test.
4. Regression gates: full Maven suite + `AdversarialValidationTest` (recall ≥0.95 / precision
   ≥0.90 / Pearson r ≥0.5 on the synthetic battery) + fraud-gate/ai-brain pytest.
5. Cache replay: 0 decision mismatches, latency before/after.
6. Card: PR-AUC, recall@FPR, then k6 CAPTURE-path numbers. Retrieval: fixed-harness recall@5,
   verdict precision, majority-vote, p50/p95.
7. Model card: version, base, params, data manifest sha256, artifact sha256, eval_loss (internal
   split — labelled as such), all measured tables. No number without an artifact.

## 8. Run order (when training is authorized — nothing below has been run)

```bash
PY=build-check/fraud-gate-venv/Scripts/python.exe
# 0. data already prepared & verified (no mining yet); re-run with v4 mining on the real pass:
$PY fraud-gate/training/retrain_v5.py --authorized-data --steps l4-data
# 1. train v5 (256 tokens, CPU-hours) + in-domain calibration
$PY fraud-gate/training/retrain_v5.py --authorized-data --steps l4-train
# 2. semantic-only evals v4 vs v5 (test / external-test / external-full)
$PY fraud-gate/training/retrain_v5.py --authorized-data --steps l4-eval
# 3. external-calib threshold selection (score_l4_onnx.py choose_threshold on l4_v5_external_calib.jsonl)
# 4. end-to-end Java evals at the selected operating points
$PY fraud-gate/training/retrain_v5.py --authorized-data --steps l4-java-eval --java-eval
# 5. card gate + k6 CAPTURE verification; retrieval after the harness fix; wire trainer (new file)
$PY fraud-gate/training/retrain_v5.py --authorized-data --steps card,retrieval --neural-retrieval
```

## 9. What v5 must NOT do

- No threshold selection on external-test; no training on any eval slice (prep enforces, 0 leakage).
- No real-data quality claims for the synthetic credit brain; no real PayPal/cards; no production
  or hosted-deployment claims; no "300 ms achieved" (target only).
- No multilingual base ≥100M params; no runtime change that breaks the WordPiece/ONNX contract
  without a measured Java parity check.
- No retrieval quality claim from the current (invalid) full_corpus scenario.
- No number in any resume-facing document without a measurement artifact behind it.