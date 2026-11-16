# CHIMERA Checkout Shield - Observability

**Status: UNTESTED.** These configs have not been run against live services.
**SANDBOX ONLY.** No numbers are prefilled anywhere: dashboards and scrape
configs populate only once real metrics are scraped. Nothing here is a measured
or benchmarked result.

## Layout

```
observability/
  prometheus.yml                                  # scrape config
  alerts.yml                                      # alert rules (must be mounted, see below)
  docker-compose.observability.yml                # postgres/redis exporters + alerts mount (compose override)
  grafana/provisioning/datasources/prometheus.yml # Grafana datasource
  grafana/provisioning/dashboards/dashboards.yml  # Grafana dashboard provider
  grafana/dashboards/chimera-checkout.json        # checkout dashboard
  grafana/dashboards/{platform-api,fraud-gate,system}.json
tools/metric_contract.py                          # fails when a dashboard/alert uses a metric nobody emits
```

## Running Prometheus + Grafana via docker compose

The **main agent owns `compose.yaml`** and will add `prometheus` and `grafana`
services. The intended wiring (service names match the existing compose network):

```yaml
  prometheus:
    image: prom/prometheus:v2.54.1
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./observability/alerts.yml:/etc/prometheus/alerts.yml:ro   # prometheus.yml's rule_files points here
    ports:
      - "127.0.0.1:9090:9090"
    # depends_on: platform-api

  grafana:
    image: grafana/grafana:11.2.0
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin   # local demo only; change for shared use
      GF_AUTH_ANONYMOUS_ENABLED: "false"
```

Then open Prometheus at `http://localhost:9090` and Grafana at
`http://localhost:3000` (dashboard folder **CHIMERA**, uid `chimera-checkout`).
The datasource points at `http://prometheus:9090` (compose service name).

## Metric sources (verified against the current source)

The dashboard uses Micrometer metric names. As of reading the codebase, the
platform-api side is wired up; these configs themselves are still **untested**
(never run against live metrics):

- `http_server_requests_seconds_count` / `_bucket` and `jvm_memory_used_bytes`:
  `micrometer-registry-prometheus` is in `platform-api/pom.xml`, and
  `application.yml` exposes `health,info,prometheus,metrics`, so
  `/actuator/prometheus` serves them.
- **`_bucket` series**: `application.yml` sets
  `management.metrics.distribution.percentiles-histogram.http.server.requests=true`
  (plus SLO buckets), so the P95/P99 `histogram_quantile` queries have data.
- `cache_gets_total{result="hit"}`: registered by `cache/OrderCache.java`
  (`Counter.builder("cache.gets").tag("result","hit"|"miss")`, tag
  `cache=checkout-order`). `CheckoutService.get` uses it for cache-aside reads.
- `chimera_idempotency_duplicates_total`: registered by
  `idempotency/IdempotencyService.java` and incremented on a completed-key
  replay. `CheckoutController.create` reads the `Idempotency-Key` header.
- **fraud-gate `/metrics` exists** (`prometheus_client`, see the comments in `prometheus.yml`) and the
  scrape jobs `fraud-gate` (:8001, HTTP) and `fraud-gate-grpc` (:8082) are enabled. The app emits
  `chimera_fraud_gate_*` names: `chimera_fraud_gate_model_loaded`, `chimera_fraud_gate_scores_total{action,fallback}`
  and `chimera_fraud_gate_score_latency_ms_bucket` (**milliseconds**). Dashboards and alerts were
  rewritten to those names; the earlier `fraud_gate_*` names never existed.
- **Metric names that are still unverified:** `fraud_gate_redis_connected` and the
  `fraud_gate_{fusion,card,temporal,biometric,evidence}_score` / `fraud_gate_llm_delta` histograms. Panels
  and the `FraudGateRedisDown` rule that use them are marked UNVERIFIED until the real names are confirmed.
- **Exporters:** `pg_*` and `redis_*` need postgres_exporter / redis_exporter, deployed by
  `docker-compose.observability.yml`. Without them the `postgres` and `redis` jobs are down and the alerts
  `ScrapeJobMissing` / `ExporterDown` fire on purpose.
- `ai-brain` has no `/metrics` (404); its job stays disabled. `node-exporter` is not deployed.

## Verify before trusting a panel

```bash
# what the services really expose
python tools/metric_contract.py names --exposition fraud-gate=http://localhost:8001/metrics
# fail on any dashboard/alert metric or label that is not exposed
python tools/metric_contract.py check \
  --dashboards observability/grafana/dashboards --rules observability/alerts.yml \
  --exposition platform-api=http://localhost:8080/actuator/prometheus \
  --exposition fraud-gate=http://localhost:8001/metrics \
  --exposition fraud-gate-grpc=http://localhost:8082/metrics
```
Add the `cadvisor`, `postgres` and `redis` endpoints as `--exposition JOB=URL` to cover those panels.

## Dashboard panels

1. Request rate (RPS) - `sum(rate(http_server_requests_seconds_count[5m]))`
2. Latency P95/P99 - `histogram_quantile(...)` over `http_server_requests_seconds_bucket`
3. Error rate (5xx) - 5xx count / total count
4. JVM heap used - `jvm_memory_used_bytes{area="heap"}`
5. Cache hit ratio - hit gets / total gets
6. Idempotency duplicates prevented - `increase(chimera_idempotency_duplicates_total[5m])`

Panels show **no data** until the prerequisites above are met and traffic flows. Run the contract check above
before concluding that a panel is merely waiting for traffic.
Thresholds/targets are to be measured, never assumed.