// CHIMERA Checkout Shield - write-path saturation probe. SANDBOX / STUB ONLY.
// Unlike checkout-load.js this removes the think-time sleep and holds a fixed
// concurrency, so the achieved http_reqs rate approximates the SUSTAINED WRITE
// CEILING of the deployed stack (bounded by the global audit-chain advisory lock
// and the HikariCP pool), not a think-time-limited arrival rate.
//
// Run:
//   k6 run -e TARGET_URL=http://localhost:8080 -e SAT_VUS=30 -e SAT_DURATION=30s \
//     loadtest/k6/saturation.js
//
// Auth/checkout contracts identical to checkout-load.js (stub demo creds
// client/demo-pass/CUSTOMER; currency USD; amount 0.01..10000). The thresholds
// here are DEGRADATION GUARDS (error rate), not latency targets: the point is to
// MEASURE the ceiling and observe where errors/latency break, not to pre-pass.
// ES5.1-compatible k6 syntax.

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

var TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';
var SAT_VUS = parseInt(__ENV.SAT_VUS || '30', 10);
var SAT_DURATION = __ENV.SAT_DURATION || '30s';

var createFailed = new Rate('create_failed');
var authorizeFailed = new Rate('authorize_failed');
var createLatency = new Trend('checkout_create_latency', true);

export var options = {
  scenarios: {
    saturation: {
      executor: 'constant-vus',
      vus: SAT_VUS,
      duration: SAT_DURATION
    }
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    create_failed: ['rate<0.05']
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
  var headers = {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + data.token
    }
  };
  var amount = Math.round((Math.random() * 99 + 1) * 100) / 100;
  var createBody = JSON.stringify({
    amount: amount, currency: 'USD', note: 'k6 saturation probe', purpose: 'CHECKOUT'
  });

  var createRes = http.post(TARGET_URL + '/api/checkout/orders', createBody, headers);
  createLatency.add(createRes.timings.duration);
  var createOk = check(createRes, { 'create status 200': function (r) { return r.status === 200; } });
  var id = createRes.status === 200 ? createRes.json('id') : null;
  createFailed.add(!createOk || id === null);
  if (id === null) { return; }

  var authRes = http.post(TARGET_URL + '/api/checkout/orders/' + id + '/authorize', JSON.stringify({}), headers);
  var authOk = check(authRes, { 'authorize status 200': function (r) { return r.status === 200; } });
  authorizeFailed.add(!authOk);
  // No sleep: back-to-back iterations to saturate the write path.
}