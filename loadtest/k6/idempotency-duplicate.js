// CHIMERA Checkout Shield - idempotency duplicate probe. SANDBOX ONLY. UNTESTED.
// Sends the SAME Idempotency-Key header twice for the SAME body and checks the
// second response is a REPLAY (same order id), counting duplicates prevented.
//
// Run:
//   k6 run -e TARGET_URL=http://localhost:8080 loadtest/k6/idempotency-duplicate.js
//
// Behavior verified in source: CheckoutController.create reads the Idempotency-Key
// header and delegates to IdempotencyService.execute. A COMPLETED key with the
// SAME body replays the stored OrderView (same id) and increments the
// chimera_idempotency_duplicates_total counter; the same key with a DIFFERENT
// body is rejected (422), and an in-flight key conflicts (409). This script sends
// an identical body twice, so the second response should be a replay (same id).
//
// The k6 Counter below mirrors the server metric NAME for local correlation; the
// authoritative chimera_idempotency_duplicates_total is scraped from
// platform-api /actuator/prometheus (see observability/). This script is UNTESTED
// (never run against a live target).
//
// THRESHOLDS ARE TARGETS TO BE MEASURED, NOT ACHIEVED RESULTS.
// ES5.1-compatible k6 syntax.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

var TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';

var duplicatesPrevented = new Counter('chimera_idempotency_duplicates_total');
var replayMismatch = new Rate('idempotency_replay_mismatch');

export var options = {
  scenarios: {
    duplicates: {
      executor: 'per-vu-iterations',
      vus: 5,
      iterations: 20,
      maxDuration: '2m'
    }
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.05'],
    idempotency_replay_mismatch: ['rate<0.01']
  }
};

export function setup() {
  var url = TARGET_URL + '/api/auth/login';
  var payload = JSON.stringify({ username: 'client', password: 'demo-pass', role: 'CUSTOMER' });
  var params = { headers: { 'Content-Type': 'application/json' } };
  var res = http.post(url, payload, params);
  var ok = check(res, { 'login status 200': function (r) { return r.status === 200; } });
  if (!ok) {
    throw new Error('Login failed against ' + url + ' (status ' + res.status + '). SANDBOX stub creds only.');
  }
  return { token: res.json('token') };
}

export default function (data) {
  // Unique key per iteration; the SAME key is reused for both requests below.
  var key = 'k6-' + __VU + '-' + __ITER + '-' + Date.now();
  var body = JSON.stringify({
    amount: 25,
    currency: 'USD',
    note: 'k6 idempotency probe',
    purpose: 'CHECKOUT'
  });
  var headers = {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + data.token,
      'Idempotency-Key': key
    }
  };

  var first = http.post(TARGET_URL + '/api/checkout/orders', body, headers);
  var second = http.post(TARGET_URL + '/api/checkout/orders', body, headers);

  check(first, { 'first create 200': function (r) { return r.status === 200; } });
  var firstId = first.status === 200 ? first.json('id') : null;
  var secondId = second.status === 200 ? second.json('id') : null;

  // Replay expectation: same key + same body => same order id (no new charge).
  var isReplay = firstId !== null && secondId !== null && firstId === secondId;
  if (isReplay) {
    duplicatesPrevented.add(1);
  }
  check(second, { 'second is a replay (same id)': function () { return isReplay; } });
  replayMismatch.add(!isReplay);

  sleep(0.5);
}