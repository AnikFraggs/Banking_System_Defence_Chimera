// CHIMERA Checkout Shield - checkout load test. SANDBOX ONLY. UNTESTED.
// Ramping VUs create + authorize STUB orders against a deployed sandbox target.
// Never point this at production or use real cards / real PayPal accounts.
//
// Run:
//   k6 run -e TARGET_URL=http://localhost:8080 loadtest/k6/checkout-load.js
//
// Auth confirmed from AuthController.java: POST /api/auth/login with body
// {username, password, role}. Demo CUSTOMER creds are client / demo-pass /
// CUSTOMER (seeded in AuthService). Response field "token" is the bearer token.
// Checkout confirmed from CheckoutController.java + CheckoutDtos.java:
//   POST /api/checkout/orders            {amount, currency, note, purpose}
//   POST /api/checkout/orders/{id}/authorize
// currency MUST be "USD" (CheckoutService rejects others); amount 0.01..10000.
//
// THRESHOLDS BELOW ARE TARGETS TO BE MEASURED, NOT ACHIEVED RESULTS.
// ES5.1-compatible k6 syntax (var/function, no arrow funcs/template literals).

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

var TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';

var loginFailed = new Rate('login_failed');
var createFailed = new Rate('create_failed');
var authorizeFailed = new Rate('authorize_failed');
var createLatency = new Trend('checkout_create_latency', true);

export var options = {
  scenarios: {
    ramping_checkout: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },
        { duration: '1m', target: 10 },
        { duration: '30s', target: 0 }
      ],
      gracefulRampDown: '30s'
    }
  },
  thresholds: {
    // Targets, not results. Tune after measuring the sandbox deployment.
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
    login_failed: ['rate<0.01'],
    create_failed: ['rate<0.05']
  }
};

export function setup() {
  var url = TARGET_URL + '/api/auth/login';
  var payload = JSON.stringify({ username: 'client', password: 'demo-pass', role: 'CUSTOMER' });
  var params = { headers: { 'Content-Type': 'application/json' } };
  var res = http.post(url, payload, params);
  var ok = check(res, { 'login status 200': function (r) { return r.status === 200; } });
  loginFailed.add(!ok);
  if (!ok) {
    throw new Error('Login failed against ' + url + ' (status ' + res.status +
      '). Expected stub demo creds client/demo-pass/CUSTOMER on a SANDBOX target.');
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

  // Random amount in [1.00, 100.00], 2 decimals, within the server's bounds.
  var amount = Math.round((Math.random() * 99 + 1) * 100) / 100;
  var createBody = JSON.stringify({
    amount: amount,
    currency: 'USD',
    note: 'k6 sandbox load test order',
    purpose: 'CHECKOUT'
  });

  var createRes = http.post(TARGET_URL + '/api/checkout/orders', createBody, headers);
  createLatency.add(createRes.timings.duration);
  var createOk = check(createRes, { 'create status 200': function (r) { return r.status === 200; } });
  var id = null;
  if (createRes.status === 200) {
    id = createRes.json('id');
  }
  createFailed.add(!createOk || id === null);
  if (id === null) {
    sleep(1);
    return;
  }

  // In stub mode getOrder returns APPROVED, so authorize settles to a 200
  // (SCORED/STEP_UP/CAPTURED depending on the model). Defensive blocks or state
  // conflicts can yield 409; those count toward http_req_failed and are exactly
  // what this test is meant to MEASURE, not pre-pass.
  var authRes = http.post(TARGET_URL + '/api/checkout/orders/' + id + '/authorize', JSON.stringify({}), headers);
  var authOk = check(authRes, { 'authorize status 200': function (r) { return r.status === 200; } });
  authorizeFailed.add(!authOk);

  sleep(1);
}