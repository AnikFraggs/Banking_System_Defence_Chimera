# CHIMERA Checkout Shield - Observability

## Verified 2026-11-16

Local Docker sandbox only. All 10 configured Prometheus targets were UP. The live audit checked 71 dashboard/rule expressions with zero metric-contract errors, warnings or skipped jobs; all 17 alert rules reported healthy evaluation. Four promtool alert fixtures passed, including missing targets, a reachable exporter with a failed database connection, and millisecond latency thresholds.

The service suite passed 71 tests with one image-only skip (including both inclusive ±0.05 delta boundaries and violations on either side); the skipped local distillation-loader check passed separately on Windows, alongside the other data/helper tests (10 total). Grafana rendered charts remain **NOT_VERIFIED**: the external Browser Connector was disconnected. A healthy Grafana scrape is not proof that its UI renders correctly. Grafana logs show dashboard provisioning completed, but also report a duplicate `xychart` registration and rejection of the legacy Angular pie-chart plugin; none of these four dashboards reference those plugins. These warnings were not hidden by relaxing Grafana security.

Evidence: `build-check/observability_live_strict_20261116.json` (warnings, skipped coverage and unhealthy rules also fail), `build-check/observability_live_final_20261116.json`, `build-check/observability_capture_20261116.json` and their logs. The initial k6 run (3 VUs, 60 seconds) captured 139/142 simulated orders; all 139 receipt signatures were valid. Three orders failed closed to STEP_UP with `GATE_TIMEOUT` while model export/parity work shared this host. The <1% capture-failure target **failed** (2.11%); HTTP success alone did not imply settlement success. Authorize-to-capture P95 was 379.18ms. This is a bounded sandbox observation, not a production capacity claim. The same 3-VU/60-second run repeated after training and evaluation finished captured **160/160 orders**, with **160/160 valid receipts**, zero HTTP failures across 481 requests, and authorize P50/P95 **112.17/129.88ms**. All three k6 thresholds passed. Evidence: `build-check/observability_capture_steady_20261116.{json,log}`. This does not erase the earlier failure or prove its cause; 160 successes do not establish a production <1% failure rate with statistical confidence. The latency trend includes all authorize attempts, including challenges in the first run.

The load script's custom summary writes only measurements, checks and run state, excluding authentication setup data. Use `CAP_SUMMARY` for an evidence file; avoid k6's legacy `--summary-export`, which also serializes setup data. The initial generated report was scrubbed of that field without changing measured values.

## Run and verify

From the repository root:

```sh
docker compose up -d --build
python observability/verify_live.py --output build-check/observability_live.json
python observability/test_metric_contract.py
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker run --rm -v "${PWD}/observability:/work:ro" -w /work --entrypoint promtool prom/prometheus:v2.54.1 test rules test_alerts.yml
```

Git Bash may require `MSYS_NO_PATHCONV=1` for Docker commands containing Linux paths. The Python live verifier uses local Prometheus on port 9090 and reads actual exporter expositions through the existing Compose network. It never fabricates metrics. `metric_contract.py check --strict` fails on warnings **and skipped coverage**; this lexical checker supplements, not replaces, Prometheus's query parser.

Prometheus: `http://localhost:9090`. Grafana: `http://localhost:3001`, folder **CHIMERA**. Sign in locally using the configured account; never paste credentials into reports or chat. Dashboards retain UIDs `chimera-checkout`, `chimera-platform-api`, `chimera-fraud-gate`, and `chimera-system`.

For bounded settlement traffic:

```sh
docker run --rm --network chimera-checkout-shield_default -v "${PWD}/loadtest/k6:/scripts:ro" grafana/k6:0.55.0 run -e TARGET_URL=http://platform-api:8080 -e CAP_VUS=3 -e CAP_DURATION=60s /scripts/capture-settlement.js
```

Use only the local stub sandbox. The script checks CAPTURED state and receipt validity, not just HTTP status; non-capture results log state and reason codes. Do not use the uploaded chaos script unchanged: its free-form shell execution, process cleanup and IP-change assumptions were not adopted.

The post-load Prometheus value snapshot is `build-check/observability_postload_metrics_20261116.json`: observed completed gRPC CAPTURE score responses, deterministic worker publications, a last informational delta of −0.0325, and `pg_up=redis_up=1`. These are real backend series, not a screenshot or per-test settlement totals; scoring can occur more than once per order and counters span process lifetimes.

## Metric meanings and limits

- `chimera_fraud_gate_scores_total{action,fallback}` counts **completed score responses**, not incoming requests or settlements. `fallback` is a boolean. HTTP and gRPC have separate registries and scrape `transport` labels.
- `chimera_fraud_gate_model_loaded` describes the **card model**, not the Java L4 guard. Both scoring transports are scraped.
- `chimera_fraud_gate_score_latency_ms` is service processing time in **milliseconds**; it excludes Java/network/settlement time.
- `chimera_fraud_gate_fusion_score` and `chimera_fraud_gate_component_score{component}` are real observations in [0,1]. Registered zero counters are not synthetic requests.
- Worker metrics count successfully published explanation results. `mode=backend_configured` does **not** prove the backend succeeded: individual debate parties may use deterministic fallback. Publication is not proof that platform-api consumed or persisted the result.
- Signed delta histograms do not expose `_sum` in the Python client. The dashboard uses the last observed delta only after an observation, plus a counter of values outside both inclusive ±0.05 bounds. These deltas remain informational and never change settlement.
- Historical matches can legitimately remain zero when no labelled cases exist. Idle histograms have no quantiles; idle cache ratios are undefined. They are not replaced with invented values.
- PostgreSQL/Redis status uses `pg_up`/`redis_up`, not just `up`. This probes **exporter-to-database** reachability, not each application's connection. Exporter ports are internal-only. The PostgreSQL exporter currently uses the sandbox application account; shared deployments should supply a dedicated least-privileged account.
- cAdvisor 0.49.1 could not discover Docker 29 overlayfs containers. Pinned `ghcr.io/google/cadvisor:0.55.1` restored named containers. CPU charts report **cores**, not the incorrect quota/period percentage. Disk/network rates use bytes/s. The memory ratio is empty for containers with no positive limit; the bytes chart remains valid.
- The 5xx ratio is zero when traffic exists but no 5xx series has ever been created; absent/idle traffic remains unobserved/undefined. PostgreSQL activity is tuples/s, not cumulative totals.
- Alert rules include missing targets, model absence, fail-closed fallback scoring and absent named-container discovery. Prometheus evaluates them, but **notification delivery is not configured** (no Alertmanager target).

## Kubernetes

See `deploy/k8s/validate_local.py` and its README. gRPC/worker metrics ports are exposed through internal Services. Twenty rendered local resources passed structural checks, but `kind` is absent; no cluster, Kubernetes load, ingress/HPA, or Kubernetes monitoring stack is claimed as tested.
