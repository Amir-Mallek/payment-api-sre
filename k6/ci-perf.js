// k6 performance test run by the CI pipeline against the ephemeral container (1 min 30 s, 50 VUs).
//   k6 run -e BASE_URL=http://localhost:8000 --summary-export=k6-summary.json k6/ci-perf.js
// Objective (OK): p95 < 200 ms and errors < 1 %. Non-critical: p95 200-500 ms or errors 1-2 %.
// Critical (pipeline fail): p95 > 500 ms or errors > 2 %. The thresholds below are the critical ones:
// crossing them aborts the test at once (fail fast); scripts/quality_gate.py classifies the rest.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
// Business errors (404, 422) are expected answers; only 5xx and timeouts count as failures.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

export const options = {
  stages: [
    { duration: '20s', target: 50 },
    { duration: '1m', target: 50 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    http_req_duration: [{ threshold: 'p(95)<500', abortOnFail: true, delayAbortEval: '15s' }],
    http_req_failed: [{ threshold: 'rate<0.02', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

const CARDS = ['4111111111111111', '5555555555554444', '378282246310005'];
const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };

export default function () {
  const r = Math.random();
  let res;
  if (r < 0.4) {
    res = http.get(`${BASE_URL}/api/v1/products`, { tags: { name: 'products' } });
  } else if (r < 0.6) {
    res = http.get(`${BASE_URL}/api/v1/products/${1 + Math.floor(Math.random() * 3)}`, { tags: { name: 'product' } });
  } else {
    const body = JSON.stringify({
      product_id: 1 + Math.floor(Math.random() * 3),
      quantity: 1,
      currency: 'EUR',
      card_number: CARDS[Math.floor(Math.random() * CARDS.length)],
    });
    res = http.post(`${BASE_URL}/api/v1/payments`, body, { ...JSON_HEADERS, tags: { name: 'payment' } });
  }
  check(res, { 'no server error': (x) => x.status < 500 });
  sleep(0.5);
}
