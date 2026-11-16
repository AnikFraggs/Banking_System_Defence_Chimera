// CHIMERA Checkout Shield - full settlement path under load. SANDBOX / STUB ONLY.
// Each iteration starts a simulator "benign" session (simulated, non-card-data
// features), authorizes it, and expects the CAPTURE saga to finish with a signed
// receipt. This is the only script that exercises L1-L6 + fraud-gate CAPTURE +
// saga + receipt signing; manual orders (checkout-load.js) carry no card
// features and fail closed to STEP_UP by design.
//
// Run:
//   k6 run -e TARGET_URL=http://localhost:8080 -e CAP_VUS=10 -e CAP_DURATION=1m \
//     loadtest/k6/capture-settlement.js
//
// Contracts (SimulatorController / CheckoutController / ReceiptController):
//   POST /api/simulator/sessions          {scenarioId, telemetry}  -> OrderView (CREATED)
//   POST /api/checkout/orders/{id}/authorize {telemetry}           -> OrderView (CAPTURED)
//   GET  /api/receipts/{id}                                        -> {valid: true}
// Thresholds are DEGRADATION GUARDS for a measured run, not achieved results.
// ES5.1-compatible k6 syntax.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

var TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';
var CAP_VUS = parseInt(__ENV.CAP_VUS || '10', 10);
var CAP_DURATION = __ENV.CAP_DURATION || '1m';
var THINK_S = parseFloat(__ENV.CAP_THINK_S || '1');

var captureFailed = new Rate('capture_failed');
var receiptInvalid = new Rate('receipt_invalid');
var captured = new Counter('orders_captured');
var settleLatency = new Trend('authorize_to_capture_latency', true);

var TELEMETRY = {
  keystrokeIntervalsMs: [112, 98, 143, 120, 105, 131],
  keystrokeDwellMs: [81, 77, 92, 85, 79, 88],
  mouseMovements: [{ dx: 14, dy: -3, dtMs: 16 }, { dx: 9, dy: 2, dtMs: 17 }]
};

export var options = {
  scenarios: {
    settlement: {
      executor: 'constant-vus',
      vus: CAP_VUS,
      duration: CAP_DURATION
    }
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    capture_failed: ['rate<0.01'],
    receipt_invalid: ['rate<0.01']
  }
};

export function setup() {
  var url = TARGET_URL + '/api/auth/login';
  var payload = JSON.stringify({ username: 'client', password: 'demo-pass', role: 'CUSTOMER' });
  var res = http.post(url, payload, { headers: { 'Content-Type': 'application/json' } });
  if (!check(res, { 'login status 200': function (r) { return r.status === 200; } })) {
    throw new Error('Login failed against ' + url + ' (status ' + res.status + '). SANDBOX stub creds only.');
  }
  return { token: res.json('token') };
}

export function handleSummary(data) {
  var report = JSON.stringify({ metrics: data.metrics, root_group: data.root_group, state: data.state }, null, 2);
  var outputs = { stdout: report + '\n' };
  if (__ENV.CAP_SUMMARY) {
    outputs[__ENV.CAP_SUMMARY] = report;
  }
  return outputs;
}

export default function (data) {
  var headers = {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + data.token }
  };
  var start = http.post(TARGET_URL + '/api/simulator/sessions',
    JSON.stringify({ scenarioId: 'benign', telemetry: TELEMETRY }), headers);
  var id = start.status === 200 ? start.json('id') : null;
  check(start, { 'simulator session 200': function (r) { return r.status === 200 && id !== null; } });
  if (id === null) {
    captureFailed.add(true);
    sleep(THINK_S);
    return;
  }

  var auth = http.post(TARGET_URL + '/api/checkout/orders/' + id + '/authorize',
    JSON.stringify({ telemetry: TELEMETRY }), headers);
  settleLatency.add(auth.timings.duration);
  var state = auth.status === 200 ? auth.json('state') : null;
  var isCaptured = state === 'CAPTURED' && auth.json('receiptAvailable') === true;
  check(auth, { 'authorize -> CAPTURED with receipt': function () { return isCaptured; } });
  captureFailed.add(!isCaptured);
  if (!isCaptured) {
    console.warn(JSON.stringify({ status: auth.status, state: state,
      action: auth.status === 200 ? auth.json('action') : null,
      reasons: auth.status === 200 ? auth.json('reasons') : null }));
    sleep(THINK_S);
    return;
  }
  captured.add(1);

  var receipt = http.get(TARGET_URL + '/api/receipts/' + id, headers);
  var valid = receipt.status === 200 && receipt.json('valid') === true;
  check(receipt, { 'receipt signature valid': function () { return valid; } });
  receiptInvalid.add(!valid);
  sleep(THINK_S);
}
