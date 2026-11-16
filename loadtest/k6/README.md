# CHIMERA Checkout Shield - k6 load tests

**Status: UNTESTED SCAFFOLDING.** These scripts have not been run against a live
target. **SANDBOX ONLY** — never point them at production, and never use real
cards, real cardholder data, or real PayPal accounts. Orders are created in
PayPal `stub` mode with seeded demo credentials.

**All thresholds are TARGETS TO BE MEASURED, not achieved results.** A passing
or failing threshold is an observation about a specific run, never a claim about
the system's performance. No benchmark numbers are prefilled or implied.

## Scripts

| Script | What it does |
| --- | --- |
| `checkout-load.js` | Ramping VUs log in, then create + authorize stub orders (`POST /api/checkout/orders`, `POST /api/checkout/orders/{id}/authorize`). |
| `idempotency-duplicate.js` | Sends the SAME `Idempotency-Key` twice for the same body; checks the second response is a replay (same order id) and counts duplicates prevented. |
| `cache-hit.js` | Seeds one order, then repeatedly `GET /api/checkout/orders/{id}` to exercise the read path / cache-aside. |

## Prerequisites

- [k6](https://k6.io/docs/get-started/installation/) installed locally, or use the
  manual `loadtest-k6` job in `.github/workflows/ci.yml` (workflow_dispatch only).
- A reachable **sandbox** deployment (e.g. `docker compose up` from the repo root,
  platform-api published on `http://localhost:8080`).
- Stub demo login: `client` / `demo-pass` / `CUSTOMER` (seeded by `AuthService`).
  Confirmed against `AuthController.java`: `POST /api/auth/login` with body
  `{username, password, role}` returns `{token, ...}`; use `Authorization: Bearer <token>`.

## Run

```
k6 run -e TARGET_URL=http://localhost:8080 loadtest/k6/checkout-load.js
k6 run -e TARGET_URL=http://localhost:8080 loadtest/k6/idempotency-duplicate.js
k6 run -e TARGET_URL=http://localhost:8080 loadtest/k6/cache-hit.js
```

`TARGET_URL` defaults to `http://localhost:8080` if unset. Override VUs/duration
with k6 flags (e.g. `--vus 20 --duration 2m`) or edit the `options.scenarios`.

In CI, trigger **CI -> Run workflow** and supply the `target_url` input (and pick
`k6_script`). The job only runs on `workflow_dispatch`, never on push/PR.

## Endpoint / metric notes (verified against the current source)

Confirmed by reading the source; the scripts themselves are still UNTESTED
(never run against a live target):

- **Idempotency-Key IS read by `CheckoutController.create`** and delegated to
  `IdempotencyService.execute`. A completed key + identical body replays the
  stored `OrderView` (same id); a different body is rejected (422); an in-flight
  key conflicts (409). `idempotency-duplicate.js` sends an identical body twice,
  so the second response should be a replay.
- **`chimera_idempotency_duplicates_total` exists** (registered by
  `IdempotencyService`, incremented on replay). The k6 `Counter` of the same name
  is a local stand-in; the authoritative metric is scraped from
  `/actuator/prometheus`.
- **Cache-aside exists:** `CheckoutService.get` uses `OrderCache` (Redis),
  registering `cache.gets` -> `cache_gets_total{result="hit"|"miss"}`.
  `cache-hit.js` repeatedly reads one id to exercise the hit path (TTL ~30s).
- **Authorize outcomes vary:** in stub mode `getOrder` returns `APPROVED`, so
  authorize settles (200). Defensive blocks or state conflicts can return 409;
  those count toward `http_req_failed` and are meant to be measured.
- `currency` must be `USD` and `amount` within `0.01..10000` (server-validated).

## Reading results

k6 prints threshold pass/fail and metric summaries at the end of a run. Treat
them as measurements of that run only. Correlate with the Grafana dashboard in
`observability/` (which also requires the instrumentation above to show data).