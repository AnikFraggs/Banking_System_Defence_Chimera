# CHIMERA Fraud Gate

Pre-capture gate for CARD authorizations. It fuses the maximum of four explainable components: a loaded creditcard HistGradientBoosting (or optional ONNX Runtime) model, backward-only device velocity/fan-out, robust biometric uniformity (keystroke interval/dwell + mouse), and evidence artifact heuristics with bounded local image forensics (FFT/EXIF, optional OCR callback). There is no synchronous LLM call; the gate is served over REST **and** gRPC from one shared decision service.

## Run

```bash
python -m venv .venv
. .venv/bin/activate             # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export MODEL_ARTIFACT_PATH=/absolute/path/creditcard_hgb.joblib
uvicorn app.main:app --host 0.0.0.0 --port 8080        # REST
python -m app.grpc_server                               # gRPC on 0.0.0.0:50051
python -m app.worker                                    # async debate + case memory
```

Or build `docker build -t chimera-fraud-gate .` and mount the model at `/artifacts/creditcard_hgb.joblib`. The service starts without an artifact but `/ready` returns 503 and every score fails closed to `CHALLENGE`; no heuristic model substitute is used.

- `POST /score/pre-capture` (REST) and `FraudGate/ScorePreCapture` (gRPC) share `app.decision_service.DecisionService`, so the two transports cannot drift into different decisions.
- `GET /ready`: reports model load state and version.
- `QUICK_RECHECK`: skips evidence/OCR analysis and uses only `context.prior_evidence_score`.
- Optional `REDIS_URL`: publishes explanations after the response. `EXPLANATION_BACKEND_URL` is an optional async HTTP debate backend; deterministic prosecutor/defense arguments are the fallback. Debate, retrieval, LoRA verdicts, and the ±0.05 delta never change score or settlement.

## Optional runtime controls

- `SAFE_LCB_POLICY_PATH`: a STEP_UP-only artifact that can only escalate `CAPTURE`→`CHALLENGE` above the trained threshold; never downgrades `VOID`.
- `GRAPH_COUNTERS_ENABLED=true`: Redis rolling graph counters (read strictly-prior, write after the response); a store failure falls back to in-request history.
- `CASE_BI_ENCODER_MODEL` + `CASE_CROSS_ENCODER_MODEL`: both set enables neural retrieval; otherwise deterministic hashed-vector matching is used.
- `MODEL_ARTIFACT_PATH=.../model.onnx`: loads an ONNX Runtime card model with a strict JSON sidecar (`features`, `version`, `threshold`).

## Train and evaluate

Raw data and model artifacts are deliberately not bundled. Supply a local Kaggle-format `creditcard.csv` with `Time`, `V1`..`V28`, `Amount`, and binary `Class`. Missing/non-finite values are rejected, not zero-filled.

```bash
python -m training.train_creditcard_hgb \
  --data /absolute/path/creditcard.csv \
  --output /absolute/path/creditcard_hgb.joblib \
  --version creditcard-hgb-YYYYMMDD --max-fpr 0.01
python -m training.evaluate_creditcard_hgb \
  --data /absolute/path/creditcard.csv \
  --artifact /absolute/path/creditcard_hgb.joblib --max-fpr 0.01
```

Training sorts by `Time`, uses temporal 70%/15%/15% splits, selects threshold only on validation within the FPR budget, and evaluates once on held-out test data. Both commands print held-out recall, precision, FPR, and single-request card-gate p50/p95/p99 latency. No performance metrics are claimed until these commands are run on real data.

The joblib artifact is one dictionary: `model` (a fitted `HistGradientBoostingClassifier`), ordered `features`, `version`, and `threshold`. Loading validates all four plus estimator feature count. Request features must match exactly; missing, extra, non-finite, or failed inference returns `CHALLENGE` with `fallback=true`.

Additional offline tools under `training/` synthesize hard negatives, fit a conservative Safe-LCB STEP_UP threshold, train a compact quantized L4 encoder, and prepare LoRA/contrastive data. They require explicit `--authorized-input` flags and never download or auto-deploy anything.

## Tests

```bash
pytest -q
```

Tests use synthetic data and a deterministic fake estimator injected through `create_app`; production loading accepts only a real joblib HistGradientBoosting artifact (or a validated ONNX artifact with a sidecar).
