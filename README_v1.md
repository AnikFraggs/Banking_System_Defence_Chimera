# CHIMERA Checkout Shield — Version 2 (v2.0.0)

> **Version 2 — released 2026-11-16.** Supersedes Version 1.1 (`f2c3cb5`). The previous release is preserved in [`README_v1.md`](README_v1.md); tag `v2.0.0` marks this release. See [What changed since Version 1.1](#what-changed-since-version-11) below.

CHIMERA Checkout Shield is a local-first, defensive checkout reference application. A Spring Boot backend coordinates PayPal-style order creation, authorization, capture, and void operations; a FastAPI fraud gate makes the synchronous pre-capture decision over **gRPC (default) or REST**; an asynchronous prosecutor/defense debate, signed receipts, and analyst review provide an audit trail.

> **Sandbox only — never use real cards, real cardholder data, or real PayPal buyer/merchant accounts.** Use the default stub or PayPal sandbox test accounts only. This is not a production payment system.

No production model, raw Kaggle data, real-data evaluation result, or latency benchmark is bundled. In particular, **CAPTURE is not possible until a real, operator-trained creditcard HistGradientBoosting (HGB) artifact is mounted**. A missing or invalid model fails closed to `CHALLENGE`.

> **Update 2026-11-14:** a card HGB artifact trained on the **real local ULB `datasets/creditcard.csv`**
> now exists (`fraud-gate/artifacts/creditcard_hgb.joblib`, 29 features), plus a PaySim wire artifact
> (`paysim_wire_hgb.joblib`, synthetic). Both load through the strict runtime contract, and measured
> rival benchmarks (XGBoost/LightGBM, ProtectAI DeBERTa-v3) with provenance/CIs are in
> [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md). The artifact must still be mounted for CAPTURE; the
> PaySim/credit-brain synthetic caveats and the sandbox-only rule are unchanged.

> **Update 2026-11-15:**
> - `ai-brain` triage now unions its regex signatures with a **hybrid RAG retriever** (BM25 +
>   bge-small int8 dense + reciprocal rank fusion + a fitted reranker), escalate-only. On the held-out
>   test split it escalates 62.7% of attacks instead of 17.1%, at a benign escalation rate of 1.59%
>   instead of 0.86%.
> - The credit brain default is now **v3** (LightGBM trees served in pure Python), synthetic data only.
> - L4 v7/v7b and the two-model ensembles were measured and **not adopted**.
> - **Superseded 2026-11-16:** the mounted card model reports `creditcard-hgb-ulb-sk1.6.1`, readiness succeeds, and sandbox CAPTURE with valid receipts is measured below. Missing/invalid features still fail closed; this is not a production-readiness claim.
> - Details: [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md) §1, §3.3–§3.4, §4.2 and §5.1. Genuine
>   datasets still missing are listed in §9.1.

## What changed since Version 1.1

Version 1.1 shipped the checkout core with deterministic guards and **no trained models mounted**. Version 2 turns it into a fully trained, measured, observable local stack:

1. **Trained models are now mounted and measured.** Card HGB on the real local ULB creditcard data plus PaySim wire HGB load through the strict runtime contract; sandbox CAPTURE with valid signed receipts is measured end-to-end. New auxiliary layers (account-opening XGBoost, AML HGB, web-attack TF-IDF LR) are wired into the backend and scraped by Prometheus. The credit brain default moved to v3 (LightGBM in pure Python, synthetic-only).
2. **L4 semantic guard: distilled v6 deployed, research candidates honestly rejected.** The 33M-parameter `l4_v6_distill_minilm_l12` int8 ONNX guard runs in-process with a WordPiece tokenizer, verdict cache, 250 ms timeout, and fail-safe CHALLENGE on any unavailability. v7/v7b, v8, v9-A, v9-hybrid and v10 were trained on the RX 9070 XT (ROCm) and benchmarked under frozen protocols — none beat the deployed baseline on the adoption gates, so nothing was replaced. All results, blind spots (burial/URL-encode/ROT13 obfuscation, encoded-benign FPR), and rival comparisons (ProtectAI DeBERTa-v3 still dominates external SPML recall) are documented in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md).
3. **Hybrid RAG triage in ai-brain.** Regex signatures now union with a BM25 + bge-small int8 dense + RRF + fitted-reranker retriever (escalate-only): held-out attack escalation 17.1% → 62.7% at 1.59% benign escalation.
4. **Checkout hardening.** Saga compensation, transactional outbox (25/25 delivered), idempotency dedupe, and verdict caching verified live; server authorize p95 ~98 ms, create ~38 ms under the k6 probe.
5. **Full observability stack.** Prometheus (10/10 targets up), Grafana with 4 provisioned dashboards (checkout, fraud-gate, platform-api, system), cAdvisor, Jaeger tracing, and exporters — all verified live with probe traffic; measured latency/transaction readouts recorded in [`BENCHMARK.md`](BENCHMARK.md).
6. **Professional frontend rebuild.** Tailwind CSS v4 design system, lean sidebar with header identity chip, richer main-content KPIs (e.g. Approvals metrics row), L4 parameter panel in Evaluation, and the root-cause fix for the desktop layout bug (an in-flow sidebar overlay consumed the grid's sidebar track, squeezing the workspace into the corner). Mobile drawer behavior preserved; hidden injection trap retained.
7. **Deployment scaffolds, honestly labelled.** `loadtest/k6` harness (source of the measured benchmark numbers), `deploy/k8s` overlay (20 resources structurally validated, never applied), and `infra/terraform` are included but explicitly **DEFERRED to the deployment phase** — the running, measured system is the local `compose.yaml` stack.
8. **New datasets wired with provenance.** Feedzai bank-account fraud, IBM AMLworld, and web-attack datasets feed the auxiliary layers and evaluation; raw data, trained artifacts, and local binaries stay out of git (see `.gitignore` Version 2 policy). No SSN/CPN-like strings in synthetic data; sandbox-only rules unchanged.

Invariants preserved from Version 1.1: escalate-only async LLM cap (±0.05), fail-closed missing-evidence CHALLENGE, no transport fallback, no threshold selection on test, no training on eval slices or SPML, `--authorized-data` trainer gate.

## L4 candidate evaluation — 2026-11-16

**v8 was trained and evaluated, but NOT promoted.** It initializes from v6 and uses the full replay set plus 3,000 new ProtectAI-scored rows, trained on the RX 9070 XT with ROCm. Under a frozen expanded three-calibration protocol, v8 improves recall on all three holdouts, but new-data FPR is **3.6%**, above the **2%** gate (v6: 2.6%). External ranking quality also regressed. CPU tokenization + int8 ONNX P95 is 13.31ms, which does not compensate for the quality failure.

The baseline and deployed L4 artifacts are unchanged; no test-threshold tuning or SPML training was used. The new comparison is not directly comparable to historical v6 58.8% recall because its calibration policy is stricter. See [MODEL_BENCHMARKS.md §3.5](MODEL_BENCHMARKS.md#35-v8-guarded-v6-replay--new-protectai-scored-data-2026-11-16-not-adopted) for the full paired results, data exclusions and limitations.

## L4 v9 research candidate — trained, NOT adopted (2026-11-16)

The Qwen proposal was adapted into an isolated v8-initialized dual-view MiniLM (payload 128 / system+payload 192), with reliability-gated ProtectAI + v6-retention distillation and a training-side grouped lexical/monotone stacker. It was trained on the RX 9070 XT (ROCm) and benchmarked under a locked 1%-calibration / 2%-test protocol against v6, v8 and ProtectAI.

**Result: the hybrid does not beat the existing models, so nothing was replaced.** FPR stays ≤2% and CPU P95 is ~13ms, but recall regresses vs both v6 and v8: the stacker overfits its meta split (external recall .116→.024) and the paired/B view learns nothing usable (ProtectAI-B flags 96.75% of external benigns when a system prompt is present). The plain neural v9-A beats v6 on every holdout but still trails v8 on external SPML (.116 vs .210), and **ProtectAI dominates external SPML recall (.968)** — the 33M student does not close that gap. v6 remains the best prior-protocol deployable student.

Caveats: No Robots is CC-BY-NC-4.0 (research-only, not commercially cleared); synthetic rule pairs are authored templates, not human-reviewed SPML; Prompt Guard/XSTest are gated and unused; the hybrid is not implemented in the Java runtime. Baseline and deployed artifacts are unchanged. Full table, gates, export-parity note and tradeoffs: [MODEL_BENCHMARKS.md §3.6](MODEL_BENCHMARKS.md).

## L4 v10 obfuscation round + canary loop — 2026-11-16 (NOT adopted; canary shipped)

Claude's six proposals (`build-check/new_l4_claude/`) were tested. A 23-transform **obfuscation matrix** on the deployed v6 shows real blind spots (burial/url-encode/rot13 recall ≈ 0) *and* an "encoded-looking ⇒ malicious" shortcut (hex/spaced/html benign FPR ≈ 1.0). **Multi-view max-pool** recovers recall but pushes FPR to **0.396 on plain benign** — not deployable. The **balanced-augmentation candidate v10** (v6 replay + 15 transforms at p=0.30, both labels augmented equally, 7 transforms held out), retrained on the **correct v6 base** (33M MiniLM-L12; an earlier 11M-base run was a confound and was corrected), **regresses external recall .587 → .336** at FPR .019 even after 14 epochs — **fails the adopt-only-if-better gate**. HackAPrompt pair data is prepared leakage-safe (18,660-row forbidden-eval guard, 0 overlaps) but the pair route needs a >128-token contract change (the v9-B paired view already failed).

**Shipped: the canary labeling loop** (`fraud-gate/app/canary_guard.py`, wired into `debate.py`/`worker.py`). A fresh HMAC canary per LLM call; a confirmed leak in backend output discards the LLM argument, forces the informational delta to 0, escalates the case, and harvests the inbound text as a labelled positive. **Operator-enabled, default OFF** — active only when `CANARY_SECRET` (≥16 bytes) is set in the environment; never stored in the repo. It cannot catch polite scope violations (nothing leaks). 14 tests pass; the ±0.05 async cap and escalate-only invariants are preserved.

**Honest open gap:** SPML G1 (native recall ≥0.50 @ FPR≤2%) is still **unmet** (v6 ≈0.42). The missing ingredient is labelled *polite scope-violation* data and a scope-conditioned signal — not obfuscation robustness. **v6 remains deployed and unchanged.** The full deployed L4 parameter set is now shown in the web "Labeled validation" page. Details: [MODEL_BENCHMARKS.md §3.7](MODEL_BENCHMARKS.md).

## Monitoring validation — 2026-11-16

The corrected monitoring stack has **10/10 scrape targets UP**, **71 live dashboard/rule expressions checked without contract errors**, and **17 healthy alert rules**. Real score/component/worker metrics, PostgreSQL/Redis exporters, and Docker-29-compatible cAdvisor are integrated. See [observability/README.md](observability/README.md) for meanings, commands and evidence.

The first bounded k6 settlement run captured **139/142 orders**; every captured order had a valid receipt. Three orders failed closed with `GATE_TIMEOUT`, so the <1% capture-failure target **failed** (2.11%) while model export/parity shared the host. No timeout or safety threshold was relaxed. A second identical bounded run after model jobs finished **passed: 160/160 captures, 160/160 valid receipts, zero HTTP failures, authorize P95 129.88ms**. Both runs are retained; neither is a production-capacity claim. Grafana rendered UI is **not verified** (Browser Connector disconnected), Kubernetes cluster testing is **blocked by missing kind**, and Alertmanager notification delivery is not configured.

## Architecture

```text
React web
   | same-origin /api through nginx in the web container
   v
Spring Boot platform-api (Java 21) ----------------> PostgreSQL
   | request defense (L1-L6), ownership/RBAC, orders, audit, receipts
   |
   | create / get approval / authorize
   | INITIAL score -> QUICK_RECHECK when needed
   | CAPTURE / CHALLENGE+step-up / VOID
   |
   | gRPC (default) via FraudGate/ScorePreCapture   -- or --  REST POST /score/pre-capture
   v
FastAPI fraud-gate (REST :8001 / gRPC :50051)  <---- shared DecisionService
   | creditcard HGB (joblib) OR int8-quantized ONNX + temporal graph features
   | + biometric uniformity + evidence/image forensics
   | concurrent scoring (card / temporal / biometric / evidence)
   | optional Safe-LCB step-up tightening, Redis rolling counters
   |
   | best-effort publish only after the score response
   v
Redis stream fraud-gate:explanations
   |
   v
python -m app.worker (fraud-gate-worker)
   | async prosecutor/defense debate -> deterministic Judge -> ±0.05 delta (never settlement)
   | case retrieval + Redis graph-augmented centroid memory; analyst-verdict ingestion
   |
   v
Redis stream fraud-gate:explanations:results   +   fraud-gate:analyst-verdicts
```

- `platform-api` owns provider operations and settlement state. It calls the fraud gate through `FraudGateTransport`; a `CAPTURE` initial decision must also pass `QUICK_RECHECK` before capture. `CHALLENGE` issues a local demo step-up challenge, while `VOID` voids the authorization.
- The fraud gate fuses the loaded HGB score, backward-only temporal graph features, robust telemetry checks, and evidence-artifact signals. Model or inference failures never become an implicit allow.
- **Transport:** gRPC/Protobuf is the default (`FRAUD_GATE_TRANSPORT=grpc`, contract in [`contracts/fraud_gate.proto`](contracts/fraud_gate.proto)). REST is explicitly selectable (`FRAUD_GATE_TRANSPORT=http`) and there is **no silent fallback** between transports. Both gate transports share one `DecisionService`, so they cannot drift into different decisions.
- **Latency is a budget, not a benchmark.** The synchronous fraud-gate timeout defaults to **300 ms per gate call**, and the in-process L4 semantic guard targets **8–12 ms**. Neither is an achieved end-to-end payment latency claim.
- Checkout does **not** depend on the `ai-brain` service: AI-layer severity refinement through it is escalate-only and falls back locally when it is down. Its triage unions regex signatures with a hybrid RAG retriever; without the gitignored bge-small encoder it runs regex-only and says so in `/health`. `ai-brain` also serves a credit-application fraud scorer (v3 LightGBM trees; CPN synthetic identity, tradeline boosting, credit sweeps, approval packages) trained on **synthetic data only**; see [`ai-brain/README.md`](ai-brain/README.md). `bff-express` is the Compose API gateway on port 5000, forwarding authenticated API requests with upstream keep-alive and bounded concurrency.

### Defense layers (Java `defense-pipeline`)

| Layer | Responsibility |
|---|---|
| L1 | IP reputation / rate limits |
| L2 | Role and account status |
| L3 | Purpose allow-list (privilege escalation is stopped here) |
| L4 | Injection & leak scanning, plus an optional in-process quantized ONNX semantic guard (<100M params) |
| L5 | Contextual human verification (invoice-discrepancy step-up, not static OTP only) |
| L6 | Deception vault / honeypot |

The L4 semantic guard keeps generative LLMs **off the critical path**: it is an in-process, dynamically int8-quantized encoder run through ONNX Runtime with a WordPiece tokenizer. When the model/vocab artifacts are absent, the deterministic L4 baseline remains active. The deployed guard is **v6** (distilled MiniLM-L12 int8, 33M params), mounted at `fraud-gate/training/artifacts/l4_semantic_guard_v6` and re-qualified in Java on 2026-11-16; the prior codesagar-v1 guard is retained at `artifacts/l4_semantic_guard` for rollback. See [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md).

### Auxiliary research layers (Python `fraud-gate`, escalate-only)

Three optional scoring layers sit beside the pre-capture card gate and **do not change the card decision**. Each is loaded from a read-only artifact directory and fails closed to `CHALLENGE` (step-up, never block) when its artifact is absent or its features are invalid:

| Layer | Endpoint | Artifact dir (env) | Model |
|---|---|---|---|
| Account-opening fraud | `POST /score/account-opening` | `ACCOUNT_OPENING_MODEL_DIR` | XGBoost on Feedzai BAF (synthetic) |
| AML laundering | `POST /score/aml` | `AML_MODEL_DIR` | HistGradientBoosting on IBM AMLworld HI-Small (synthetic) |
| Web-attack text | `POST /score/web-attack` | `WEB_ATTACK_MODEL_DIR` | TF-IDF char n-gram + LogisticRegression |

`GET /ready/aux` returns 200 when at least one layer is loaded, else 503. In `compose.yaml` the artifacts mount at `/aux-artifacts` from `fraud-gate/training/artifacts/`. All three were trained under scikit-learn 1.6.1 (the deployed card runtime) with calibration-only thresholds; measured holdouts, baselines, and synthetic-data caveats are in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md) ("Auxiliary defence layers"). They emit `chimera_aux_layer_*` Prometheus metrics and appear on the CHIMERA Fraud Gate Grafana dashboard (panels 13–17). These are **synthetic-data research layers**, not proof of real-world accuracy; separate integration and real-data qualification are required before any production claim.

### Asynchronous explanations are not settlement inputs

After returning a score, the fraud gate makes a best-effort Redis publish. The separate worker consumes `fraud-gate:explanations` with a consumer group, runs a constrained **Prosecutor vs. Defense** debate adjudicated by a deterministic **Judge**, retrieves similar past cases (hash-vector fallback or optional neural bi-encoder + cross-encoder rerank), and writes `decision_id`/`explanation`/`payload` entries to `fraud-gate:explanations:results`. Any LLM influence is clamped to **±0.05** and is asynchronous only — it never changes the score, capture, challenge, or void outcome. Deterministic templates are the fallback when no debate backend is configured.

Explanation delivery can be delayed or lost without changing the score, capture, challenge, or void outcome. To inspect the five newest result entries locally:

```bash
docker compose exec redis redis-cli XREVRANGE fraud-gate:explanations:results + - COUNT 5
```

### Optional runtime controls

- `SAFE_LCB_POLICY_PATH` — an offline-trained conservative lower-confidence-bound step-up policy that can only escalate `CAPTURE`→`CHALLENGE`; it never weakens high-risk voids or downgrades friction.
- `GRAPH_COUNTERS_ENABLED=true` — Redis rolling device-velocity/fan-out counters (read strictly-prior, write after the response).
- `CASE_BI_ENCODER_MODEL` + `CASE_CROSS_ENCODER_MODEL` — both set enables neural case retrieval; otherwise deterministic hashed-vector matching is used.
- `MODEL_ARTIFACT_PATH=.../model.onnx` — load an ONNX Runtime card model with a strict JSON sidecar instead of joblib.

## Run locally with Docker Compose

Prerequisites: Docker with Compose v2. Python 3.12 is also required only when training the model outside a container.

From the repository root:

```bash
cp .env.example .env
mkdir -p fraud-gate/artifacts
docker compose up --build
```

PowerShell equivalents for the first two commands:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force fraud-gate/artifacts
```

Compose starts `postgres`, `redis`, `fraud-gate` (REST), `fraud-gate-grpc`, `fraud-gate-worker`, `platform-api`, and `web`. Published ports bind to `127.0.0.1` for local use.

| Surface | URL |
|---|---|
| React web | http://localhost:5173 |
| Platform API health | http://localhost:8080/actuator/health |
| Fraud gate readiness (REST) | http://localhost:8001/ready |
| Auxiliary layers readiness | http://localhost:8001/ready/aux |
| Fraud gate OpenAPI | http://localhost:8001/docs |
| Fraud gate gRPC | 127.0.0.1:50051 |
| Prometheus | http://localhost:9090 |
| Grafana (CHIMERA Fraud Gate dashboard) | http://localhost:3001 (admin/admin) |
| Jaeger traces | http://localhost:16686 |

The auxiliary research layers and the L4 v6 semantic guard load from read-only mounts under `fraud-gate/training/artifacts/` (`account_opening_fraud`, `aml_laundering`, `web_attack_guard`, `l4_semantic_guard_v6`). They are included by default; if an artifact is absent the corresponding layer fails closed to `CHALLENGE` (aux) or the deterministic L4 baseline (semantic guard). These mounts are separate from the operator-supplied card model in `fraud-gate/artifacts/`.

Local seeded identities are `client` / `demo-pass` with role `CUSTOMER`, and `accountant` / `demo-pass` with role `ACCOUNTANT`. They are demo credentials, not an authentication design for deployment.

**Expected no-model behavior:** `/ready` returns 503 and Compose can report the fraud gate as unhealthy while its API remains available. The other services still start. Orders can exercise stub creation/authorization and fail-closed `CHALLENGE`, but no valid capture or captured receipt is produced. Do not substitute a synthetic production model to make the demo capture.

Useful lifecycle commands:

```bash
docker compose ps
docker compose logs -f platform-api fraud-gate fraud-gate-grpc fraud-gate-worker
docker compose down
# Remove local PostgreSQL/Redis data only when it is safe to discard it:
docker compose down -v
```

## Required real model for CAPTURE

Compose mounts exactly:

```text
./fraud-gate/artifacts:/artifacts:ro
```

The configured artifact is `/artifacts/creditcard_hgb.joblib` (or an ONNX model with a sidecar). The gate loads it once at process startup. Supply an authorized local Kaggle-format `creditcard.csv` containing `Time`, `V1` through `V28`, `Amount`, and binary `Class`; the project neither downloads the dataset nor bundles raw data or a production artifact. Check the dataset license and authorization before use.

From `fraud-gate/` with Python 3.12:

```bash
python -m venv .venv
source .venv/bin/activate             # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m training.train_creditcard_hgb \
  --data /absolute/path/creditcard.csv \
  --output /absolute/path/to/repository/fraud-gate/artifacts/creditcard_hgb.joblib \
  --version creditcard-hgb-YYYYMMDD \
  --max-fpr 0.01

python -m training.evaluate_creditcard_hgb \
  --data /absolute/path/creditcard.csv \
  --artifact /absolute/path/to/repository/fraud-gate/artifacts/creditcard_hgb.joblib \
  --max-fpr 0.01
```

Training sorts by `Time`, uses chronological 70%/15%/15% train/validation/test partitions, selects a threshold on validation within the FPR budget, and evaluates on the held-out test partition. The evaluation command prints measured held-out classification and card-inference latency values; none are prefilled here.

A measured run on the real ULB file is recorded in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md) §1. Its artifact, `fraud-gate/training/benchmarks/card/creditcard_hgb_ulb.joblib` (29 features: `V1`–`V28`, `Amount`), is **not promoted**. On this host `fraud-gate/artifacts/` still holds a synthetic toy that expects `Time` as well, so every card score fails closed (see "Where improvements are needed", item 3). To promote the measured artifact, copy it to `fraud-gate/artifacts/creditcard_hgb.joblib` and restart as below.

After placing the real artifact, restart the gate so it reloads once:

```bash
docker compose restart fraud-gate fraud-gate-grpc
curl --fail http://localhost:8001/ready
```

A loaded model is necessary but not sufficient: the fused initial and quick-recheck decisions must both permit capture. Keep the artifact and dataset out of source control.

## PayPal configuration

### Default: explicit local stub

`.env.example` selects:

```dotenv
PAYPAL_MODE=stub
VITE_PAYPAL_STUB=true
```

The backend stub records create/get/authorize/capture/void operations against local order state. It does not contact PayPal, load the PayPal SDK, move money, or represent a real buyer approval. In the Postman flow, `POST /api/checkout/orders/{id}/authorize` is the explicit simulated approval and authorization action. Leave PayPal secrets empty in stub mode.

For a browser stub flow with local Vite, stop the Compose web container to free port 5173, then run:

```bash
docker compose stop web
cd web
npm ci
VITE_API_URL=http://localhost:8080 VITE_PAYPAL_STUB=true npm run dev
```

On PowerShell, set `$env:VITE_API_URL="http://localhost:8080"` and `$env:VITE_PAYPAL_STUB="true"` before `npm run dev`.

### Optional: PayPal sandbox HTTP

Use only newly created **sandbox** test applications and sandbox test accounts. Set backend values in `.env`:

```dotenv
PAYPAL_MODE=http
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_CLIENT_SECRET=your-sandbox-client-secret
PAYPAL_WEBHOOK_ID=your-sandbox-webhook-id
```

For local Vite, use `VITE_PAYPAL_STUB=false` and set `VITE_PAYPAL_CLIENT_ID` to the sandbox client ID. The client ID is a public browser identifier; **never put `PAYPAL_CLIENT_SECRET` in any `VITE_` variable or React code**. Restart `platform-api` after backend changes and restart/rebuild Vite after browser build-time changes.

Compose passes `VITE_PAYPAL_STUB`, `VITE_PAYPAL_CLIENT_ID`, and the optional `VITE_PAYPAL_SDK_URL` into the web build. After changing them, run `docker compose up --build web` so the browser bundle is rebuilt.

The remote HTTP gateway accepts the PayPal sandbox HTTPS endpoint, not a live PayPal endpoint. In HTTP mode, buyer approval must occur through the PayPal sandbox buttons before the backend authorize call; the backend checks provider status and performs authorize/capture/void server-side. Webhook IDs and webhook processing must also come from the sandbox configuration. Container and hosted-browser verification remain pending.

## Checkout API and Postman

Import [`postman/CHIMERA-Checkout-Shield.postman_collection.json`](postman/CHIMERA-Checkout-Shield.postman_collection.json). Its defaults target `http://localhost:8080` and `http://localhost:8001`, and its inherited bearer token is populated by the local customer-login request.

Run the folders in order:

1. Local customer/analyst login and fraud readiness.
2. Benign simulated stub order creation, get order, simulated approval/authorize, scored order, and receipt when available.
3. A separate `bot-checkout` step-up flow using the backend-returned six-digit `demoOtp`.
4. The six scenario starts and scenario catalog.
5. Analyst recent-order listing with the `ACCOUNTANT` token.

The receipt request intentionally requires a previously captured order. A 404 after fail-closed challenge is expected; do not treat it as a reason to bypass the model requirement.

### Six scenario labels

| ID | What it exercises |
|---|---|
| `benign` | Human-like telemetry and simulated card features on a low-risk path |
| `card-testing-burst` | Prior device velocity/fan-out leading to authorization void on a high-risk decision |
| `bot-checkout` | Uniform input timing, step-up verification, and rescore |
| `injection-note` | Prompt-injection text stopped by request defense before provider creation |
| `privilege-escalation` | Customer principal attempting a manager-only purpose |
| `ai-receipt` | Simulated generator/evidence markers and analyst review |

All scenarios are simulations, not real attacks or real payment activity. Their final risk state still depends on the configured model and decision path.

## Audit and deployment secrets

- Empty `AUDIT_HMAC_KEY` is allowed only for local ephemeral use: a random key is generated and old signatures do not survive a restart with a different key.
- Persistent/shared deployments require a long random `AUDIT_HMAC_KEY`, a stable `AUDIT_KEY_VERSION`, a strong `MANAGER_AUTH_KEY`, and a strong `POSTGRES_PASSWORD`.
- Deception-vault rows (`deception_vault_entries`) are sealed with AES-256-GCM under a key derived from `AUDIT_HMAC_KEY` (HKDF-SHA256). With an empty key the vault key is ephemeral too, so stored rows cannot be decrypted after a restart.
- `.env` is local configuration. Do not commit it, PayPal credentials, raw datasets, or model artifacts.

## Tests and CI

```bash
# Java 21 multi-module tests
mvn -B test

# PostgreSQL integration tests (Testcontainers, needs Docker; see the note below)
mvn -B verify -Pintegration -pl platform-api -am -DargLine="-Dapi.version=1.44"

# Python 3.12 fraud-gate tests (no production model required)
cd fraud-gate
pytest -q
cd ..

# Python 3.12 ai-brain tests (5 hybrid-RAG tests skip without the bge-small encoder)
cd ai-brain
python -m pytest tests -q
cd ..

# Locked frontend install and production build
cd web
npm ci
npm run build
```

`.github/workflows/ci.yml` runs the Java, fraud-gate and web jobs on Java 21, Python 3.12, and Node 22, plus a non-blocking `verify -Pintegration` job and the platform-api image build. `.github/workflows/ai-brain.yml` runs the ai-brain tests, an import smoke and the ai-brain image build; CI has no encoder, so it tests regex-only triage. The root `Dockerfile` builds the jar with `-Dmaven.test.skip=true`: tests run in the local and CI gates, not in the image build. Unit tests may use injected synthetic fixtures; those fixtures are not production model artifacts or real-data evidence.

Known test-environment issues (2026-11-15):
- **Testcontainers 1.19.8 vs Docker Engine 29.** Docker 29 needs API ≥ 1.44, so Testcontainers reports Docker as unavailable. `@Testcontainers(disabledWithoutDocker = true)` then skips all 4 integration tests **silently** and the build stays green. Passing `-Dapi.version=1.44` to the test JVM fixes it (4/4 pass on PostgreSQL 15); the `DOCKER_API_VERSION` env var alone does not. CI is unchanged and has the same risk on Docker 29 runners. Recommended: upgrade Testcontainers, or add the property to the CI command.
- **Run `mvn clean` once after pulling.** The second Flyway migration was renamed to `V3__persistent_auth_sessions.sql` (two V2 files made Flyway refuse to start). A stale `target/classes` copy of the old V2 file breaks Flyway the same way.
- **JDK 25 hosts:** Mockito needs `-DargLine="-Dnet.bytebuddy.experimental=true"`. Java 21, as in CI, does not.
- **7 untracked work-in-progress platform-api test files** do not compile against the current main code (31 errors). `mvn test` on a working tree that contains them fails at test-compile. They are not committed, so CI does not see them. See item 11 below.

## Metrics scaffolding

[`metrics/checkout-shield.template.json`](metrics/checkout-shield.template.json) contains `null` for every unmeasured result. Copy it to a separate local results file and populate it only from retained evaluation/load-test output. Record the dataset and artifact hashes, chronological split, sample counts, environment, and evidence paths. `status: NOT_MEASURED` must not be presented as zero fraud, zero false positives, or achieved latency.

## Render blueprint (not deployed or tested)

[`render.yaml`](render.yaml) describes a Java web service, fraud-gate web service with a persistent `/artifacts` disk, explanation worker, React/nginx web service, managed PostgreSQL, and managed Key Value (Redis-compatible) storage. Stub mode remains the default. Secret-like values use `sync: false`.

Before considering a deployment:

1. Create the Blueprint in one region and provide `AUDIT_HMAC_KEY`, `MANAGER_AUTH_KEY`, and any intentionally used sandbox PayPal values.
2. Keep the fraud gate in fail-closed mode until a real artifact is uploaded to its disk as `/artifacts/creditcard_hgb.joblib`; restart it and verify `/ready` independently of the liveness check.
3. Keep `PAYPAL_MODE=stub` unless sandbox HTTP has deliberately been configured. Never switch the base URL to live PayPal.
4. Verify managed database connectivity, receipt persistence, worker stream consumption, provider behavior, and the complete browser flow before making any deployment claim.

The blueprint is an untested starting configuration, not a statement that Render deployment or browser verification has succeeded. Render paid plans are required where the blueprint uses persistent disks/worker instances. The existing web Dockerfile's PayPal build-argument limitation also applies on Render.

## What file does what

### `contracts/`

- `fraud_gate.proto` — single source of truth for the gRPC contract (`chimera.fraud.v1`, service `FraudGate/ScorePreCapture`). Java stubs are generated by `protobuf-maven-plugin`; Python stubs live in `fraud-gate/app/grpc_generated/`.

### `fraud-gate/app/` (Python 3.12, FastAPI + gRPC)

| File | Responsibility |
|---|---|
| `main.py` | REST entrypoint (`uvicorn app.main:app`). Lifespan builds the shared `DecisionService` (model, publisher, Safe-LCB policy, rolling counters) and the auxiliary layer service. Exposes `POST /score/pre-capture`, `GET /ready`, plus `POST /score/{account-opening,aml,web-attack}` and `GET /ready/aux`. |
| `grpc_server.py` | gRPC entrypoint (`python -m app.grpc_server`). Converts proto<->Pydantic and serves the same `DecisionService`. |
| `decision_service.py` | Shared async decision service used by both transports; orchestrates scoring, Safe-LCB step-up, `decision_id`, and post-response record/publish. |
| `scoring.py` | Fusion logic; runs card / temporal / biometric / evidence concurrently (`asyncio.gather`) while preserving deterministic fusion semantics. |
| `card_model.py` | Joblib HGB loader with strict artifact validation; dispatches `.onnx` paths to `OnnxCardModel`. |
| `onnx_card_model.py` | ONNX Runtime int8-quantized card model with a strict JSON sidecar (`features`, `version`, `threshold`). |
| `aux_layers.py` | Optional escalate-only research layers (account-opening XGBoost, AML HGB, web-attack TF-IDF LR); strict feature validation, fail-closed to `CHALLENGE`, `chimera_aux_layer_*` metrics. |
| `temporal_graph.py` | Backward-only device velocity/fan-out scoring from request history. |
| `biometrics.py` | Robust median/MAD biometric uniformity (keystroke interval/dwell, mouse micro-tremor). |
| `evidence.py` | Evidence-artifact heuristics plus bounded image-payload screening. |
| `image_forensics.py` | FFT spectral artifact detection, Pillow EXIF, screen-image detection, decompression-bomb guards. |
| `policy.py` | Decision fusion and the LLM delta clamp (±0.05). |
| `safe_lcb.py` | Offline Safe-LCB step-up policy; escalates `CAPTURE`→`CHALLENGE` only, never weakens voids. |
| `rolling_counters.py` | Redis rolling velocity/fan-out counters (read strictly-prior, write after response). |
| `schemas.py` | Strict Pydantic v2 request/response models. |
| `canonical.py` | Canonical sorted `key=value` telemetry serialization/parsing. |
| `investigator.py` | Deterministic explanation templates and the `ExplanationPublisher` (Redis stream). |
| `debate.py` | Async prosecutor/defense argument generation and deterministic Judge adjudication. |
| `case_matching.py` | Case retrieval: hashed-vector fallback or optional sentence-transformer bi-encoder + cross-encoder rerank. |
| `case_memory.py` | `RedisCaseMemory` — zlib-compressed centroid memory with a Lua compare-and-set. |
| `worker.py` | Redis stream consumer: runs the debate per job and ingests `analyst-verdicts` into case memory. |
| `grpc_generated/` | Generated `fraud_gate_pb2.py` / `fraud_gate_pb2_grpc.py` bindings. |
| `Dockerfile`, `requirements.txt` | Fraud-gate image and dependencies. |

### `fraud-gate/training/` (offline, requires explicit `--authorized-input`)

| File | Responsibility |
|---|---|
| `offline_common.py` | Shared loading/validation helpers for training commands. |
| `train_creditcard_hgb.py` | Chronological 70/15/15 HGB training with validation-selected threshold within the FPR budget. |
| `evaluate_creditcard_hgb.py` | Held-out evaluation and card-inference latency measurement. |
| `hard_negative_synthesis.py` | Offline synthesis: slow-drip card testing, human-like timing variance, polymorphic memos. |
| `train_creditcard_hgb_synthetic.py` | Train the HGB on synthesized hard negatives (pre-flight hardening). |
| `train_l4_semantic_guard.py` | Fine-tune/quantize the compact in-process L4 semantic encoder to ONNX. |
| `train_contrastive.py` | Fine-tune the bge-small-en-v1.5 bi-encoder for case embeddings. |
| `train_lora_verdicts.py` | Offline LoRA training on analyst verdicts. |
| `train_safe_lcb.py` | Fit the conservative STEP_UP threshold (Safe-LCB). |
| `train_account_opening.py` | Feedzai BAF account-opening XGBoost/HGB/LR; temporal month split, calibration-only threshold (`--authorized-data`). |
| `train_aml.py` | IBM AMLworld HI-Small laundering HGB/XGB/LR; train-window aggregates, matched-FPR recall comparison (`--authorized-data`). |
| `train_web_attack.py` | Web-attack TF-IDF char-n-gram LR vs defensive regex baseline; sentence-hash split (`--authorized-data`). |

### `platform-api/` (Java 21, Spring Boot 3.3.5)

| Package | Responsibility |
|---|---|
| `PlatformApplication.java` | Spring Boot entrypoint. |
| `checkout/` | Order lifecycle: `CheckoutService`, `CheckoutController`, `CheckoutDefenseService`, order/risk/step-up entities, `OrderState`. |
| `checkout/StepUpService.java`, `InvoiceDiscrepancy.java` | Contextual L5 step-up challenges computed from the exact invoice discrepancy. |
| `checkout/VerificationChallengeGenerator.java` (+ `Http*`/`Deterministic*`) | Challenge generation: HTTP hook or deterministic fallback. |
| `fraud/` | `FraudGateTransport`, `FraudGateClient` (HTTP), `GrpcFraudGateClient` + `FraudGateGrpcCodec` (gRPC), `ScoreRequest`/`ScoreResponse`/`ScoreReason`, `FraudGateFallback`. |
| `payment/` | `PayPalGateway` (stub + HTTP), webhook controller/service, operation entities. |
| `audit/` | Hash-chained HMAC audit ledger (`AuditCrypto`, `AuditLedgerService`), receipt generation. |
| `auth/` + `rbac/` | Users, roles, access nodes. |
| `cases/` | Analyst case listing, feedback publisher, async case-analysis consumer, configuration. |
| `defense/` | Wires the `defense-pipeline` layers into the API. |
| `simulator/` | Scenario catalog and simulator endpoints. |
| `banking/`, `service/`, `intelligence/`, `evaluation/`, `health/`, `config/` | Supporting surfaces (market quotes, service requests, RAG/threat intel, health scoring, web config). |

### `defense-pipeline/` (Java, request-defense layers)

| Package | Responsibility |
|---|---|
| `DefensePipeline`, `DefenseOrchestrator`, `DefenseLayer`, `DefenseResult` | Layer orchestration and result propagation. |
| `layers/L1_IpReputationLayer.java` … `layers/L6_DeceptionVaultLayer.java` | L1–L6 defense layers (see table above). |
| `detect/InjectionScanner.java`, `NestedEncodingDecoder.java`, `ConfusableNormalizer.java`, `CanaryTokenRegistry.java` | Deterministic L4 injection/leak detection primitives. |
| `detect/SemanticInjectionGuard.java`, `OnnxSemanticInjectionGuard.java`, `WordPieceTokenizer.java` | In-process ONNX semantic L4 guard and tokenizer (off the critical path). |
| `healing/`, `vault/`, `redteam/`, `validation/`, `metrics/` | Healing playbooks, deception vault, adversarial sample generation, validation harness, latency registry. |

### `common/`

- `DefenseContext`, `LayerVerdict`, `Role`, `AccessNode` — shared defense/RBAC types used by both Java modules.

### `web/` (React 18 / Vite)

| File | Responsibility |
|---|---|
| `src/App.jsx`, `src/main.jsx` | Application shell and entrypoint. |
| `src/checkout/CheckoutPage.jsx`, `PayPalCheckoutButton.jsx` | Checkout flow and PayPal SDK (sandbox) button. |
| `src/checkout/StepUpDialog.jsx` | Contextual step-up challenge UI. |
| `src/checkout/useSessionTelemetry.js` | Pre-auth continuous biometric capture (keystroke/mouse) sent to the gate. |
| `src/checkout/api.js`, `payments.js` | API client and payment helpers. |
| `src/checkout/analyst/AnalystOrdersTable.jsx` | Analyst recent-order review. |
| `src/checkout/receipts/ReceiptView.jsx` | Captured-receipt viewer. |
| `src/checkout/simulator/ScenarioCards.jsx` | Six-scenario simulator UI. |

### `ai-brain/` (Python, FastAPI; details in [`ai-brain/README.md`](ai-brain/README.md))

| File | Responsibility |
|---|---|
| `app.py` | `/v1/triage` (regex + hybrid RAG union, logistic risk, recommendation), `/v1/credit-application/score`, `/health`. |
| `rag_engine.py` | Hybrid retriever: canonicalization and PAN/email redaction, BM25, bge-small int8 ONNX encoder, RRF, logistic reranker with challenge/block bands. |
| `credit_brain.py` | Credit featurization, red-flag knowledge base, v3 tree traversal (v1/v2 LR for rollback), fail-closed `assess`. |
| `models/` | `credit_brain_v{1,2,3}.json`, `rag_reranker.json`; `bge_small/` (encoder + tokenizer) is gitignored. |
| `training/` | Synthetic credit generator and trainers (v1/v2, v3), RAG eval builder, encoder export, RAG and triage-decision benchmarks. |
| `benchmarks/` | Measured output: `credit_onnx/`, `credit_v3/`, `rag/`. |
| `tests/test_app.py` | 27 API/engine tests (5 need the encoder). |
| `Dockerfile`, `requirements.txt` | ai-brain image (copies the code and `models/`) and pinned serving dependencies. |

### Root and other

- `compose.yaml` — full local stack including `fraud-gate-grpc`.
- `.env.example` — all environment variables with safe local defaults.
- `pom.xml` — parent Maven POM for `common`, `defense-pipeline`, `platform-api`.
- `Dockerfile` — multi-stage platform-api image (builds the jar with `-Dmaven.test.skip=true`; tests run in the local/CI gates).
- `render.yaml` — untested Render blueprint.
- `postman/` — checkout API collection.
- `metrics/checkout-shield.template.json` — NOT_MEASURED metrics scaffold.
- `generate_datasets.py` — synthetic dataset generation (not production data).

## Where improvements are needed

Status as of 2026-11-15. Measured numbers live in [`MODEL_BENCHMARKS.md`](MODEL_BENCHMARKS.md)
(trained models vs rivals, newest), [`RESULTS_DOSSIER.md`](RESULTS_DOSSIER.md) (every
layer/model), [`BENCHMARK.md`](BENCHMARK.md) (load/latency), and
[`PROBLEM_STATEMENT.md`](PROBLEM_STATEMENT.md) (the v5 gap analysis). This list is kept honest:
items marked *measured* have an artifact; items marked *pending* do not.

1. **Build verification — measured (re-run 2026-11-15).** IntelliJ's bundled Maven 3 with its JBR
   (JDK 25, so the Mockito flag above is needed):
   - defense-pipeline 95 tests, 0 failures, 1 skipped;
   - platform-api 66/66, run in a scratch copy without the 7 WIP test files (item 11);
   - `EngineeringPersistenceIT` 4/4 on PostgreSQL 15 with `-Dapi.version=1.44` (Flyway V1→V3
     applied);
   - fraud-gate 60 passed, from a scratch venv (`build-check/fraud-gate-venv` points at another
     user's Python and does not start);
   - ai-brain 27 passed; without the encoder 22 pass and 5 skip.
   - Logs: `build-check/mvn_test_2026-11-15_minus_wip_bb.log`, `build-check/mvn_it_2026-11-15_*.log`.
2. **gRPC transport — exercised 2026-11-16.** The local stub settlement load traversed the gRPC gate and captured 139/142 orders with valid receipts. Three deadline failures caused `GATE_TIMEOUT` challenges, so the capture-failure target failed; see the dated monitoring results above.
3. **Models — mixed, see MODEL_BENCHMARKS.md.**
   - **Card gate — local runtime checked 2026-11-16.**
     - The offline ULB HGB benchmark achieved recall 0.827 at FPR 0.0076 (43/52 frauds); XGBoost ranked better (PR-AUC 0.767 vs 0.751).
     - The mounted artifact now reports `creditcard-hgb-ulb-sk1.6.1`; readiness and simulator CAPTURE with valid receipts were verified. It is not byte-identical to `training/benchmarks/card/creditcard_hgb_ulb.joblib`, so the earlier benchmark is not automatically evidence for this exact binary.
     - Missing/invalid card features still fail closed to `INVALID_FEATURES`. No card artifact was replaced by the current L4/monitoring work.
   - **L4 semantic guard — v6 mounted + Java re-qualified 2026-11-16.** The distilled v6 MiniLM
     (33M params, int8 ONNX) is now the mounted production guard
     (`fraud-gate/training/artifacts/l4_semantic_guard_v6`, wired in `compose.yaml`). It runs at its
     calibration-only operating point (softmax probability ≥ 3.3335e-06, logit margin −12.61, max
     calib FPR 2%), **not** the generic 0.65 default. The Java runtime was re-qualified with the real
     v6 ONNX through the full L4 layer (`L4RealDataEvaluation`, Docker Maven/Temurin-21): external
     recall 0.574 / FPR 0.016, internal recall 0.967 / FPR 0.024, p50 ~10 ms, replay 0 decision drift
     (full cache hits); `L4SemanticGateTest` 5/5 pass. The Java WordPiece tokenizer + int8 ONNX
     reproduce the Python operating point. The extra internal FPs are pre-existing deterministic
     scanner hits, and L4 is escalate-only (CHALLENGE, not block). External recall is still 0.574 vs
     0.883 for the 184M ProtectAI rival, and the native-SPML G1 gate is unmet — **mounting v6 is not a
     production-readiness claim.** The prior codesagar-v1 guard is retained at
     `artifacts/l4_semantic_guard` for rollback. See `build-check/l4_v6_mount/java_qualification.json`.
   - **Credit brain:** v3 adopted as the default, on synthetic data only.
   - LoRA verdict and Safe-LCB scripts are tooling-only, never run, no artifacts.
4. **Image forensics test coverage — pending.** Pillow-based screening test skips where Pillow is
   absent; exercise it in the Docker image.
5. **Retrieval — triage RAG deployed; case memory still a gap.**
   - **ai-brain triage (MODEL_BENCHMARKS §5.1):** the hybrid RAG raises attack escalation from 0.171
     to 0.627 on the test split, with benign escalation 0.0086 → 0.0159. Recall for T1110, T1071,
     CB-CPN and CB-TL is unmeasured (no labelled text). Lowering `CHALLENGE_WEIGHT` to 0.45 is an
     open product decision: it would route 24% of attacks to `step_up` (no human review) instead
     of `constrain`.
   - **fraud-gate case memory, measured against live Redis.** Retrieval benchmarks run on real
     Redis 7 (dossier §5): LSH candidate generation triples recall vs legacy paging (0.12 vs 0.04),
     but the `full_corpus` harness scenario is invalid (128-candidate positional truncation) and
     neural p50 latency is 5.9–9.2 s/query — both are v5 fixes. A labelled relevance benchmark (G4)
     is still not run. Async debate remains a deterministic stub (±0.05 informational); the Redis
     stream consumer loop is not integration-tested.
6. **Safe-LCB and rolling counters — pending.** Unit-tested in isolation; no trained policy artifact.
7. **Metrics — many measured, some still targets.** Measured: read 48.11 / write 14.63 req/s, server
   P95 417.67 / P99 709.23 ms, 100/100 idempotent duplicates, 99.62% cache hit, recovery 42.5 s,
   index speedups 71.76×/184.10×/1.60× (BENCHMARK.md). **Still targets, not achieved:** the 300 ms
   gate budget and 8–12 ms L4 target; checkout write P95 (530–644 ms) exceeds the 500 ms goal due to
   the global audit-chain advisory lock. Card-fraud quality is measured offline on the ULB set
   (MODEL_BENCHMARKS §1). The 2026-11-16 CAPTURE measurements above use the currently mounted `creditcard-hgb-ulb-sk1.6.1` artifact, whose hash differs from the earlier benchmark binary.
8. **PayPal sandbox and deployment — pending.** Stub-only (`PAYPAL_MODE=stub`); real sandbox
   approval/webhooks/capture/void, Render deployment, and hosted/browser verification are not done.
9. **Production controls — pending.** Local identity, demo OTP, and authorization are demonstration
   only; production auth, MFA/WebAuthn, secret management, immutable audit retention, and
   payment-grade operational controls are not implemented.
10. **Genuine datasets — to be sourced by the owner.** MODEL_BENCHMARKS §9.1 lists each missing
    source and what it unblocks:
    - gated Hugging Face items: the Llama Prompt Guard 2 model, HackAPrompt, WildJailbreak;
    - Tensor Trust (no licence) and the official BIPIA release;
    - BAF and IBM AMLworld (Kaggle credentials needed);
    - real credit-boost/CPN applications, and labelled text for 4 triage classes;
    - L5 interaction recordings and L6 vault logs;
    - PATT `IntrudersXSS.txt` (quarantined by the local antivirus);
    - the codesagar licence.

    IEEE-CIS (`datasets/new_datasets_v2/`) is present but not run yet.
11. **Work-in-progress platform-api tests — decision needed.** 7 untracked test files do not compile
    against the current main code (31 errors), e.g. `spring-security-test` is not a dependency and
    several constructors and signatures have changed:
    `auth/RegistrationControllerTest`, `auth/WithMockChimeraUser`,
    `auth/WithMockChimeraUserSecurityContextFactory`, `banking/BankServiceTest`,
    `banking/MarketQuoteServiceTest`, `evaluation/ThreatSimulationServiceTest`,
    `outbox/KafkaOutboxPublisherTest`. Update them to the current APIs, or remove them.
