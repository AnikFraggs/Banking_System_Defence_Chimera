// CHIMERA Checkout Shield - cache-aside read load. SANDBOX ONLY. UNTESTED.
// Repeatedly GETs the SAME order to exercise the read path / cache-aside.
//
// Run:
//   k6 run -e TARGET_URL=http://localhost:8080 loadtest/k6/cache-hit.js
//
// Endpoint confirmed from CheckoutController.java: GET /api/checkout/orders/{id}
// returns the OrderView. Auth: POST /api/auth/login (client/demo-pass/CUSTOMER).
//
// Behavior verified in source: CheckoutService.get uses OrderCache (cache-aside
// backed by Redis). The first read is a miss (populates the cache); subsequent
// reads of the same id are hits, incrementing cache_gets_total{result="hit"}
// (tag cache=checkout-order). Writes evict the key and the TTL defaults to ~30s,
// so sustained reads of one id exercise the hit path. This script is UNTESTED
// (never run against a live target).
//
// THRESHOLDS ARE TARGETS TO BE MEASURED, NOT ACHIEVED RESULTS.
// ES5.1-compatible k6 syntax.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

var TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';

var getFailed = new Rate('cache_get_failed');

export var options = {
  scenarios: {
    cache_reads: {
      executor: 'constant-vus',
      vus: 10,
      duration: '1m'
    }
  },
  thresholds: {
    http_req_duration: ['p(95)<300'],
    http_req_failed: ['rate<0.01'],
    cache_get_failed: ['rate<0.01']
  }
};

export function setup() {
  var loginUrl = TARGET_URL + '/api/auth/login';
  var loginPayload = JSON.stringify({ username: 'client', password: 'demo-pass', role: 'CUSTOMER' });
  var jsonHeaders = { headers: { 'Content-Type': 'application/json' } };
  var loginRes = http.post(loginUrl, loginPayload, jsonHeaders);
  var loginOk = check(loginRes, { 'login status 200': function (r) { return r.status === 200; } });
  if (!loginOk) {
    throw new Error('Login failed against ' + loginUrl + ' (status ' + loginRes.status + '). SANDBOX stub creds only.');
  }
  var token = loginRes.json('token');

  // Seed one order to read repeatedly.
  var authHeaders = {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }
  };
  var createBody = JSON.stringify({ amount: 25, currency: 'USD', note: 'k6 cache seed order', purpose: 'CHECKOUT' });
  var createRes = http.post(TARGET_URL + '/api/checkout/orders', createBody, authHeaders);
  var createOk = check(createRes, { 'seed create 200': function (r) { return r.status === 200; } });
  if (!createOk) {
    throw new Error('Could not seed an order for cache reads (status ' + createRes.status + ').');
  }
  return { token: token, id: createRes.json('id') };
}

export default function (data) {
  var headers = { headers: { 'Authorization': 'Bearer ' + data.token } };
  var res = http.get(TARGET_URL + '/api/checkout/orders/' + data.id, headers);
  var ok = check(res, { 'get status 200': function (r) { return r.status === 200; } });
  var bodyId = res.status === 200 ? res.json('id') : null;
  var matches = bodyId === data.id;
  check(res, { 'get id matches seed': function () { return matches; } });
  getFailed.add(!ok || !matches);
  sleep(0.2);
}