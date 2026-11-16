# CHIMERA Checkout Shield — Engineering Benchmark Report

## L4 v8 evaluation — 2026-11-16

The v6-initialized, ProtectAI-assisted v8 candidate was trained on 25,874 rows and evaluated under a locked three-calibration protocol. **Rejected for promotion:** new-holdout FPR 3.6% exceeds 2%, despite improved paired recall and 13.31ms CPU tokenize+int8 P95. External ROC-AUC also fell from 0.92477 to 0.88618. Baseline/deployed artifacts are unchanged. The full v6/v8 table, SPML-native diagnostic, training details and protocol caveats are in [MODEL_BENCHMARKS.md §3.5](MODEL_BENCHMARKS.md); machine-readable evidence is `build-check/l4_v8/paired_evaluation.json`.

## L4 v9 evaluation — 2026-11-16

The Qwen-adapted v9 (v8-initialized dual-view MiniLM + reliability-gated KD + grouped lexical stacker) was trained on the RX 9070 XT (ROCm) and benchmarked under a locked protocol against v6, v8 and ProtectAI. **Rejected for promotion:** the hybrid keeps FPR≤2% and CPU tokenize+int8 P95 ~13.17ms, but recall regresses vs v6 and v8 on the real holdouts; the stacker overfits its training-side meta split and the paired/B view provides no usable signal. The plain neural v9-A beats v6 everywhere yet trails v8 on external SPML; ProtectAI external recall (.968) far exceeds every student. int8 artifact 33.9MB, opset 17, FP32 eager parity verified under CPU torch (~5e-6) after a ROCm/CPU exporter tracing discrepancy. No baseline/deployed artifact changed. Research-only (No Robots CC-BY-NC-4.0); hybrid not implemented in Java. Full table and gates: [MODEL_BENCHMARKS.md §3.6](MODEL_BENCHMARKS.md); evidence `build-check/l4_v9/evaluation.json`.

## Observability integration measurement — 2026-11-16

On the Ryzen 7 9700X / RX 9070 XT host, the local Docker stub sandbox now has 10/10 Prometheus targets UP. The saved live audit covers 71 dashboard/rule expressions with zero contract errors/warnings/skips; all 17 rules evaluate successfully. Four promtool rule fixtures pass. Service regression results: 71 passed, one local-helper skip in the image; that helper passed on Windows with the remaining data/contract tests (10 total).

The first 3-VU, 60-second k6 run produced 142 orders: 139 CAPTURED, three STEP_UP with `GATE_TIMEOUT` (confirmed by grouped database query). All 139 captured-order receipts verified. HTTP failures were 0/424, but capture failure was **2.11%**, exceeding the <1% target. Authorize latency P50/P95: **196.50/379.18ms**. GPU-trained model export/CPU parity ran concurrently; this is not an isolated capacity measurement. No safety budget was increased to turn failure into a pass.

A second identical 3-VU/60-second run after the model jobs finished **passed**: **160/160 CAPTURED**, **160/160 receipts valid**, **0/481 HTTP failures**, authorize P50/P95 **112.17/129.88ms** (max 151.84ms). It passed the three existing <1% failure thresholds. This is a bounded steady-run observation, not a capacity test or proof that contention caused the first failure; 160 successes do not statistically establish production failure <1%. The authorize latency metric includes challenged attempts in the first run.

Evidence: `build-check/observability_capture_20261116.{json,log}`, `build-check/observability_capture_steady_20261116.{json,log}`, `build-check/observability_live_strict_20261116.{json,log}`. The custom k6 summary excludes login setup data; the initial report's setup field was removed without changing measurement fields. Grafana browser rendering NOT_VERIFIED (connector disconnected). Kubernetes: 20 local rendered resources structurally checked, but `kind` absent, so no cluster/API/load result. Alertmanager delivery is not configured. Details and reproduction: [observability/README.md](observability/README.md).

### Live gateway + latency/transaction readout — 2026-11-16 (post-restart probe)

After a stack restart all counters were zero, so a bounded synthetic probe was run through the
real API (24 create+authorize stub orders, 1 idempotency replay, 8 cached reads, 6 calls per aux
layer). Measured from Prometheus (`localhost:9090`) and Grafana (`localhost:3001`):

- **Gateways:** Prometheus 10/10 active targets `up`; Grafana `/api/health` `database: ok`
  (v11.2.0); datasource `Prometheus → http://prometheus:9090` health **OK**; a Grafana→Prometheus
  proxy query returned live data. Four provisioned dashboards (checkout 6, fraud-gate 16,
  platform-api 12, system 12 panels).
- **Fraud-gate score latency:** p50 **1.42 ms**, p95 **1.99 ms**, p99 **21.4 ms** over 24 scored
  requests. **Aux layer p95 0.95 ms** each (account_opening / aml / web_attack).
- **Transactions:** outbox recorded **25** / published **25** / dead **0**; idempotency duplicates
  prevented **1** (replay returned the same order id); cache gets **7 hit / 1 miss**; saga
  completed **0** because every probe order settled to `STEP_UP`, not CAPTURE.
- **Fail-closed observed, not hidden:** the 24 checkout decisions are
  `CHALLENGE{fallback=true}` on **fraud-gate-grpc** (the transport platform-api uses); the probe
  payloads carry no card/biometric evidence, so the gate fails closed to step-up exactly as
  designed. Direct aux probes with incomplete feature dicts likewise returned
  `CHALLENGE{fallback=true}` for account_opening/aml, while web_attack scored normally
  (`PASS{fallback=false}`). `chimera_fraud_gate_model_loaded=1` on both transports, so this is
  missing-evidence fail-closed, not a missing model.
- **API latency (server-side, micrometer):** authorize p95 **98 ms**, create p95 **38 ms**,
  cached read p95 **6.8 ms** for this probe. Client-observed authorize wall time was ~2.1 s p50
  (sequential urllib, cold connections); the server histogram is the authoritative service time.
  These are single-probe observations, not capacity results.

Earlier measurements below retain their original dates/environments.

> **UPDATE 2026-11-14 — model training/benchmarking supersedes parts of this report.** The card HGB
> gate is now **trained on the real local ULB CSV** and a **PaySim wire trainer exists**, both
> benchmarked against XGBoost/LightGBM on identical temporal splits; L4 v5 is fine-tuned and
> benchmarked vs ProtectAI DeBERTa-v3. The "not trained / Kaggle not fetched / no wire trainer /
> xgboost absent" statements in §9 below are **stale**. See [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md)
> for measured numbers, provenance and Wilson CIs. The k6 load measurements here remain valid; the
> 2026-11-14 follow-up changes are not yet re-load-benchmarked.

**Every number below was measured on the running system, not estimated or targeted.** Raw output
files are in [`build-check/bench/`](build-check/bench/) and are cited per section. Where a value is a
*target* rather than an achieved result, it is labelled as such. This report deliberately separates
what was measured from what was only built, and states the test environment so the numbers can be
interpreted and reproduced.

> Scope guardrails honoured throughout: **stub PayPal only** (`PAYPAL_MODE=stub`, no real sandbox HTTP
> calls, no real cards or real buyer/merchant accounts); credentials are environment-based; the card
> model and semantic guard were **not trained** (no artifacts), so the fraud gate **fails closed**;
> "temporal graph features" (no trained GNN); LLM influence capped at ±0.05 and asynchronous only;
> **300 ms is a target budget, not an achieved benchmark**.

---

## 1. Test environment

| Layer | Value (verified) |
|---|---|
| Host OS | Windows 11 Home Single Language, 10.0.26200, x64 |
| Host CPU / RAM | 13th Gen Intel Core i5-1334U, 10 cores / 12 logical, 15.7 GB |
| Container runtime | Docker Desktop 29.6.2, Linux VM: **12 vCPU, 7.60 GiB** (`MemTotal=8163368960`), `overlayfs` |
| App image | `chimera-platform-api:local` `sha256:0fdd906ee4f9…`, **488 MB (466 MiB)** |
| JVM / framework | Temurin **JDK 21.0.13+9**, Spring Boot 3.3.5, Hibernate 6.5.3, Tomcat 10.1.31 |
| DB pool | HikariCP 5.1.0 `ChimeraPool`: max **20**, min idle **5**, connection-timeout **10 s** |
| Datastores | PostgreSQL **15-alpine**, Redis **7-alpine** |
| Load generator | **k6 0.55.0** (`grafana/k6`), run in a container on the compose network, `TARGET_URL=http://platform-api:8080` |
| Observability | Prometheus v2.54.1, Grafana 11.2.0, Jaeger 1.60 (OTLP) |
| Build / unit tests | Maven 3.9.9 (host), JUnit 5 |
| PayPal mode | **stub** — order ids `STUB-ORDER-…`, auth ids `STUB-AUTH-…`; no external PayPal calls |
| Fraud gate | `fraud-gate/artifacts/` **empty** (no card model) → gate fails closed `GATE_TIMEOUT` → `CHALLENGE` / `STEP_UP`, score 0.5; `fraudGate` circuit breaker **OPEN** |

All load ran against the containerized app inside the Docker VM. **The VM (12 vCPU / 7.60 GiB), not
the 15.7 GB Windows host, bounds these results.** A live functional probe confirmed the fail-closed
path: `POST /orders` → `state=CREATED`; `POST /orders/{id}/authorize` → `state=STEP_UP`,
`action=CHALLENGE`, `reasons=[GATE_TIMEOUT]`, `captureId=null`, demo OTP issued.

---

## 2. Headline results — the eight requested metrics

| # | Requested metric | Measured result | Source |
|---|---|---|---|
| 1 | **Maximum sustained RPS** | Read path **48.11 req/s** (0% err); clean write path **14.63 req/s** (0% err, no think-time); write+1s-think **9.57 req/s** | `cache-hit.json`, `saturation10.json`, `checkout-load.json` |
| 2 | **P95 / P99 API latency** | Server all-URI **P95 417.67 ms / P99 709.23 ms**; create **P95 542.18 / P99 833.30 ms**; authorize **P95 697.29 / P99 912.98 ms**; cached read **P95 9.75 / P99 17.20 ms** | `metrics-final-idem.txt` |
| 3 | **Throughput under concurrent transactions** | 10 VUs → **578 create+authorize iterations / 1157 requests in 2 min, 0% error** | `checkout-load.json` |
| 4 | **Duplicate transactions prevented** | **100** in the k6 idempotency run (server counter 1→101), **0% replay mismatch, 0% error** | `idempotency.json`, `metrics-final-idem.txt` |
| 5 | **Recovery time after service failure** | SIGKILL + start → **health UP 42.50 s**, **functional 47.25 s** | `recover.txt` |
| 6 | **DB query latency before/after indexing** | owner_history **88.051→1.227 ms (71.76×)**; recent_feed **86.525→0.470 ms (184.10×)**; state_filter **80.228→50.001 ms (1.60×)** | `index-bench.txt` |
| 7 | **Cache hit ratio** | **99.62%** (2882 hits / 2893 gets, 11 misses), cache-aside `checkout-order`, 30 s TTL | `metrics-final-cache.txt` |
| 8 | **Error rate under load** | **0%** at ≤10 VUs (checkout-load, cache-hit, idempotency); rises under write saturation (6.38% @20 VUs, 70% @30 VUs) | `*.json`, `saturation20.json`, `saturation.json` |

---

## 3. Specific improvement #1 — concurrency deadlock fix (before → after)

Same profile (`checkout-load.js`: ramping 10 VUs, 1 s think-time, 2 min), same environment.

| Metric | **BEFORE** (lock-ordering deadlock) | **AFTER** (advisory-lock fix + pool 20) |
|---|---|---|
| `create_failed` | **82.76%** | **0%** |
| `http_req_failed` | **71.43%** | **0%** |
| Completed iterations | 28 | **578** |
| Requests (rate) | 35 (**0.25 req/s**) | 1157 (**9.57 req/s**) |
| P50 latency | **30 023.82 ms** | **248.79 ms** |
| P95 latency | **59 987.40 ms** | **644.16 ms** |
| Max latency | 59 987.60 ms | 1 252.94 ms |
| Successful-subset median | 172.05 ms (only 5 creates succeeded) | — (all succeeded) |

Sources: [`checkout-load-before.json`](build-check/bench/checkout-load-before.json) →
[`checkout-load.json`](build-check/bench/checkout-load.json).

**Root cause & fix.** A JVM `synchronized` block (released at method return) was nested inside a
Postgres `pg_advisory_xact_lock` (held until the outer transaction commits). The two locks were
acquired in inconsistent orders across threads, producing a lock-ordering deadlock: most requests
hung ~30–60 s and only 5 of 29 creates completed. The redundant `synchronized` was removed (the
advisory lock is already re-entrant and cross-process), and the Hikari pool was sized to 20. After the
fix **every** create+authorize succeeded, P50 dropped from ~30 s to **249 ms**, and throughput rose
**~38×** (0.25 → 9.57 req/s).

*Run-to-run variance:* the AFTER P95 was 529.59 ms on one run (`checkout-load-run2.log`) and 644.16 ms
on the final run (`checkout-load.json`); both are reported, neither is hidden.

---

## 4. Specific improvement #2 — idempotency `created_at` NOT-NULL 500 (found & fixed)

**Symptom.** Every `POST /api/checkout/orders` carrying an `Idempotency-Key` header returned **HTTP
500**. Server log: `update idempotency_keys set created_at=(NULL) … ERROR: null value in column
"created_at" … violates not-null constraint` (SQLState 23502, `DataIntegrityViolationException`).

**Root cause.** `IdempotencyKeyEntity` has an **assigned** `String @Id` and **no `@Version`**, so Spring
Data's `JpaMetamodelEntityInformation.isNew()` returns `false` and `save()` calls `merge()` instead of
`persist()`. `@PrePersist` stamps `createdAt` on the *managed copy*, not the original transient
instance. `IdempotencyService` reuses that original (still `createdAt=null`) for the completion save,
so the second `merge()` writes `NULL` into the NOT-NULL column and the transaction rolls back.

**Fix.** `IdempotencyKeyEntity implements Persistable<String>` with `isNew() = (createdAt == null)`,
forcing `persist()` for new rows so the `@PrePersist` timestamp survives the completion update.

**Verified (real Postgres, not mocks).**
- Rebuilt image `0fdd906ee4f9`, redeployed; live `curl` double-create with the same key → **both 200,
  same order id**, `duplicates prevented = 1`.
- k6 `idempotency-duplicate.js` (5 VUs, 100 iterations): **100 duplicates prevented**, first-create
  200 ×100, replay-same-id ×100, **`idempotency_replay_mismatch = 0`**, **`http_req_failed = 0`**,
  P95 118.19 ms. Source: [`idempotency.json`](build-check/bench/idempotency.json).

**Why tests missed it.** The mock-based unit tests never exercise a real JPA `merge()`. The
Testcontainers IT *does* cover this path but **skips on this Windows host** (see §7). The fix is
therefore evidenced by the live + load runs above against the real containerized PostgreSQL.

---

## 5. Specific improvement #3 — database index optimization

`index_bench.py` seeded **300 000 rows** into a scratch table and ran `EXPLAIN ANALYZE`, median of 5
runs, before (PK only) and after the three JPA indexes
(`idx_orders_owner_created(username, created_at)`, `idx_orders_state(state)`,
`idx_orders_created(created_at)`). Source: [`index-bench.txt`](build-check/bench/index-bench.txt) (`INDEX_EXIT=0`).

| Query | BEFORE (Seq Scan) | AFTER (Index Scan) | Speed-up |
|---|---|---|---|
| `owner_history` — `username=? ORDER BY created_at DESC LIMIT 100` | 88.051 ms | **1.227 ms** | **71.76×** |
| `recent_feed` — `ORDER BY created_at DESC LIMIT 100` | 86.525 ms | **0.470 ms** | **184.10×** |
| `state_filter` — `count(*) WHERE state=CAPTURED` | 80.228 ms | **50.001 ms** | **1.60×** |

All three plans flipped **Seq Scan → Index Scan**. The `state_filter` gain is modest (1.60×) because
`state=CAPTURED` matches ~20% of rows — low selectivity, so the index helps far less than the
owner/time-ordered lookups. This is reported honestly rather than rounded up to the headline ratios.

---

## 6. Write-path saturation — the real bottleneck (honest finding)

`saturation.js`, **no think-time**, constant VUs, 30 s, create+authorize. Sources:
[`saturation10.json`](build-check/bench/saturation10.json),
[`saturation20.json`](build-check/bench/saturation20.json),
[`saturation.json`](build-check/bench/saturation.json) (30 VUs).

| VUs | req/s | `http_req_failed` | P50 | P95 |
|---|---|---|---|---|
| **10** | **14.63** | **0%** | 617.13 ms | 1 236.45 ms |
| 20 | 1.44 | 6.38% | 10 903.01 ms | 30 916.47 ms |
| 30 | 3.15 | 70% | 10 434.27 ms | 10 668.88 ms |

**Cause: HikariCP pool starvation, not a deadlock.** At ≥20 no-think writers the app logged
`Connection is not available, request timed out after 10005ms (total=20, active=20, idle=0,
waiting=30)`. The app **recovered cleanly** afterwards (active=0, pending=0, health UP) — it fail-fasts
on connection timeout instead of deadlocking.

**Why writes serialized in the measured baseline.** `AuditLedgerService.append` took a **global**
advisory lock `pg_advisory_xact_lock(741852963)` plus `findTopByOrderByIdDesc` to build a tamper-evident
hash chain. Because the append joined the outer checkout transaction, the lock stayed held through
fraud scoring and capped measured write throughput at ~14.6 req/s. The read path takes no such lock,
which is why it sustained 48 req/s. A follow-up now commits each append in a short `REQUIRES_NEW`
transaction, keeping the global chain while releasing the lock before fraud scoring. Its actual
throughput and pool behavior remain unverified pending a repeat k6 run.

---

## 7. Reliability, outbox, saga (observed state)

From [`metrics-final-idem.txt`](build-check/bench/metrics-final-idem.txt) (cumulative end-state scrape):

- **Circuit breaker `fraudGate`:** `failure_rate = 100%`, 40 failed calls, **538 `not_permitted`**
  (short-circuited), state **OPEN**. Expected: no card model → gate fails closed → breaker trips and
  protects the API from a hanging dependency.
- **Transactional outbox:** **recorded 680 / published 680 / dead 0** — no gap, no DLQ accumulation.
  (The earlier 790/590 gap was caused by ~200 rolled-back idempotency attempts incrementing the
  recorded counter pre-commit; it disappeared after the §4 fix.)
- **Saga:** `completed = 0`, `compensated = 0` **under load** — because authorize settles to `STEP_UP`
  (fail-closed), the CAPTURE settlement saga is **not exercised by load**. Saga compensation logic is
  covered by **3 unit tests** (happy path; reverse-order compensation; compensation-failure → FAILED).

---

## 8. Testing summary

| Suite | Result | Evidence |
|---|---|---|
| **JUnit 5 unit** | **69 pass** (platform-api 52, defense-pipeline 17), 0 failures / 0 errors / 0 skipped — re-run against the fixed code, `BUILD SUCCESS`, `MVN_EXIT=0` | `build-check/bench/unit-after-fix.log` |
| **L4 real-data eval harness** | `L4RealDataEvaluation` (1 conditional test) runs only with `-Dchimera.eval.input`; passed in the dataset evaluation (§9), not part of the standard 69 | `datasets/new_custom_datasets/EVALUATION.md` |
| **Testcontainers IT** | `EngineeringPersistenceIT` (4 tests) **SKIPPED** on this Windows host; `BUILD SUCCESS`, 4 skipped | `build-check/it-skip2.log` |
| **k6 load** | 4 scenarios run (checkout-load, cache-hit, idempotency-duplicate, saturation); real numbers above | `build-check/bench/*.json` |
| **Chaos / recovery** | SIGKILL + restart → health 42.50 s, functional 47.25 s | `build-check/bench/recover.txt` |

The idempotency service unit tests (`IdempotencyServiceTest`, 6) and saga tests (`SagaOrchestratorTest`,
3) are green against the fixed code. The standard `mvn test` total is **69** (52 + 17); an earlier
disk tally of 70 mistakenly included a stale `L4RealDataEvaluation` report from the eval session.

**Testcontainers honesty.** `EngineeringPersistenceIT` is annotated
`@Testcontainers(disabledWithoutDocker=true)`. On this host Testcontainers cannot detect a valid Docker
environment — Docker Desktop's named pipe (`npipe://\\.\pipe\docker_cli`) returns a 400/empty info
response to docker-java — so all 4 IT tests **gracefully skip** (`Tests run: 4, Skipped: 4`,
`MVN_EXIT=0`). They were **not** executed against a real ephemeral Postgres here. The idempotency
regression they guard is instead verified by the live `curl` and k6 runs in §4 against the real
containerized PostgreSQL 15.

---

## 9. Dataset / model status (from [`datasets/new_custom_datasets/EVALUATION.md`](datasets/new_custom_datasets/EVALUATION.md))

- **Fetched (real, public):** `codesagar_v3` 8 760 rows from Hugging Face. Kaggle tabular sources
  (`creditcard_ulb`, `paysim`, `baf`, `ieee_cis`) were **not fetched via the Kaggle API** (no
  credentials) — **but the ULB `creditcard.csv` and PaySim CSVs are present locally in `datasets/`
  and are now trained/benchmarked (2026-11-14, see [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md))**.
  `spml` was since fetched (external held-out); `web_attack` / `baf` / `ieee_cis` remain not run.
- **Leakage-safe splits** (seed 13, hash-split): train 6 146 / dev 1 289 / test 1 257 / external_test 0.
- **Measured — deterministic L4 baseline** on 1 257 test payloads (`InjectionScanner` + canary registry;
  **no** semantic ONNX guard, **no** AI-brain refinement), after the phrasing-rule tightening:

  | Metric | Value | Wilson 95% CI |
  |---|---|---|
  | Recall | **17.8%** (46/258) | 13.6–23.0% |
  | False-positive rate | **0.30%** (3/999) | 0.1–0.9% |
  | Precision | **93.9%** (46/49) | 83.5–97.9% |

  Confusion TP=46, FP=3, TN=996, FN=212; wall time 1 450 ms (~1.15 ms/payload, single thread, JDK 21).
  **17.8% is the rule layer alone, not whole-system recall** — most `codesagar_v3` malicious rows are
  general jailbreak personas without the concrete evasion patterns the rules target. Anchoring the
  exfil verbs to a sensitive object removed 44 rule false positives (47→3; benign-`ultrachat` 43→2).
- **Measured — L4 + trained ONNX semantic guard** (dynamic-int8 WordPiece encoder, escalate-only,
  `LOCAL_ONLY` severity) on the same split: **recall 88.0%** (227/258, CI 83.4–91.4), **FPR 1.0%**
  (10/999), **precision 95.8%** (227/237); TP=227, FP=10, TN=989, FN=31. Per-row p50 10–20 ms /
  p95 23–48 ms (host-load dependent), all below the 250 ms timeout. **88.0% is an upper bound** —
  origin-style leakage (gandalf 99.1% vs deepset 66.7%) and no held-out external source. See
  [`EVALUATION.md`](datasets/new_custom_datasets/EVALUATION.md) §4/§4b.
- **Card + wire models NOW TRAINED (2026-11-14):** `fraud-gate/artifacts/creditcard_hgb.joblib`
  (real ULB, 29 features, validation threshold 0.001601) and `paysim_wire_hgb.joblib` (10 features)
  load via the strict runtime contract. The L4 semantic guard is trained/measured; v5 is fine-tuned.
  Measured rival benchmarks (XGBoost/LightGBM, ProtectAI DeBERTa-v3) + provenance are in
  [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md). Training *tooling* remains unit-tested (plumbing),
  distinct from model quality. The historical "no Kaggle CSV / artifacts empty / card gate fails
  closed for lack of a model" statement is superseded (a trained model now exists).

---

## 10. Honest caveats — what was NOT verified

- **Stub PayPal only.** No real PayPal sandbox HTTP calls, no real cards, no real buyer/merchant
  accounts. Order/auth ids are `STUB-…`.
- **No CAPTURE settlement under load.** The gate fails closed to `STEP_UP`, so the load tests measure
  `CREATED → STEP_UP`, not the full capture saga (unit-tested only).
- **Checkout write P95 (530–644 ms) exceeds the 500 ms target**, due to the global audit-chain advisory
  lock (§6). The **300 ms** figure is a *target budget*, never achieved or claimed.
- **Max RPS is profile-bounded.** Clean ceilings on this 12-vCPU / 7.60 GiB VM: ~14.6 req/s write,
  ~48 req/s read. These are not production capacity claims.
- **Testcontainers IT skipped on Windows** (§8) — not a real-Postgres regression run in this environment.
- **No production-readiness, real-PayPal, Render, or browser/hosted verification is claimed.**
- **Model quality is not claimed** for untrained artifacts (§9).

---

## 11. Reproduce

```bash
# from the repo root, with the compose stack up (PAYPAL_MODE=stub)
# k6 (container on the compose network; writes JSON + log to build-check/bench)
bash build-check/bench/run_k6.sh loadtest/k6/checkout-load.js      checkout-load
bash build-check/bench/run_k6.sh loadtest/k6/cache-hit.js          cache-hit
bash build-check/bench/run_k6.sh loadtest/k6/idempotency-duplicate.js idempotency

# write-path saturation at a chosen VU count (inline docker; run_k6.sh does not forward SAT_VUS)
MSYS_NO_PATHCONV=1 docker run --rm --network chimera-checkout-shield_default \
  -v "$PWD/loadtest/k6:/scripts:ro" -v "$PWD/build-check/bench:/output" \
  -e TARGET_URL=http://platform-api:8080 -e SAT_VUS=10 -e SAT_DURATION=30s \
  grafana/k6:0.55.0 run --summary-export /output/saturation10.json /scripts/saturation.js

# DB index before/after (300k rows, EXPLAIN ANALYZE)
python build-check/bench/index_bench.py

# recovery (SIGKILL + restart; run LAST — it resets counters)
python build-check/bench/recover_test.py

# server-side Prometheus scrape (cache ratio, duplicates, outbox, saga, P50/P95/P99, breaker)
python build-check/bench/scrape_metrics.py final-idem

# unit tests against the fixed code (host JDK 21 + Maven 3.9.9)
JAVA_HOME="C:/Users/USER/tools/jdk-21.0.13+9" \
  "C:/Users/USER/tools/apache-maven-3.9.9/bin/mvn.cmd" -B test
```

---

## Appendix — number → source map

| Claim | File |
|---|---|
| Concurrency before/after | `checkout-load-before.json`, `checkout-load.json`, `checkout-load-run2.log` |
| Idempotency 100 duplicates / 0% mismatch | `idempotency.json`, `metrics-final-idem.txt` |
| Cache 48.11 req/s, 99.62% hit | `cache-hit.json`, `metrics-final-cache.txt` |
| Write saturation 10/20/30 VUs | `saturation10.json`, `saturation20.json`, `saturation.json` |
| Server P50/P95/P99, outbox, saga, breaker | `metrics-final-idem.txt`, `metrics-final-load.txt` |
| DB index 71.76× / 184.10× / 1.60× | `index-bench.txt` |
| Recovery 42.50 s / 47.25 s | `recover.txt` |
| Unit 69 pass / IT 4 skipped | `unit-after-fix.log`, `it-skip2.log` |
| L4 det. 17.8% / 0.30% / 93.9%; +ONNX 88.0% / 1.0% / 95.8% | `datasets/new_custom_datasets/EVALUATION.md`, `out/l4_predictions_deterministic.csv`, `out/l4_predictions_onnx.csv` |

## Follow-up changes (2026-11-14; not yet load-benchmarked)

- Local login sessions now persist in PostgreSQL as SHA-256 token hashes, with expiry indexed; the
  raw bearer token is returned once and is never stored. Authenticated requests currently perform a
  database session lookup, so their throughput impact still needs a k6 comparison.
- OAuth JWT validation now enforces the configured issuer when a direct JWK URI is used and accepts
  standard enum or `ROLE_` role claims, including role arrays.
- Express BFF calls now reuse upstream HTTP connections, apply bounded request bodies/timeouts, and
  shed work above 32 in-flight requests by default with HTTP 503/`Retry-After` (tunable via
  `BFF_MAX_IN_FLIGHT`). Banking reads and transfers are delegated to
  the authenticated platform API instead of reading/writing unscoped PostgreSQL rows.
- The legacy BFF initializer adds owner/time history indexing and uses conflict-safe demo seeds.
- Hibernate SQL echo is now off by default (`DB_SHOW_SQL=true` remains available for local diagnosis),
  and Open Session in View is disabled so request rendering does not retain a persistence context.
- Audit hash-chain appends now commit in a short `REQUIRES_NEW` transaction, releasing the global
  advisory lock before checkout continues into remote fraud scoring; the pool default is 40 to allow
  checkout and audit transactions to coexist. A rollback after an external provider action may leave
  an audit event for that attempted action, which is intentional for audit durability.

These are implementation changes, not measured throughput claims. The headline figures above remain
the last measured baseline until the benchmark suite is rerun against the updated session lookup and
gateway path. Model threshold replay results and their external-set trade-off are recorded in
[`datasets/new_custom_datasets/EVALUATION.md`](datasets/new_custom_datasets/EVALUATION.md) §8.5.
