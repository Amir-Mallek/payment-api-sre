// k6 load test of payment-api: ramp-up (0 -> 100 VU), stress (500 VU), spike (1500 VU for 30 s).
// Run all scenarios:      k6 run -e BASE_URL=http://localhost:8080 load-test.js
// Run a single scenario:  k6 run -e SCENARIO=spike load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://payment-api.payment.svc.cluster.local';

// SLO: a request is "good" if HTTP status < 500. 4xx are client errors, not service failures.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

const allScenarios = {
  ramp_up: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '2m', target: 100 },
      { duration: '2m', target: 100 },
      { duration: '20s', target: 0 },
    ],
    gracefulRampDown: '10s',
    tags: { test_phase: 'ramp_up' },
  },
  stress: {
    executor: 'ramping-vus',
    startTime: '4m30s',
    startVUs: 0,
    stages: [
      { duration: '2m', target: 500 },
      { duration: '5m', target: 500 }, // prolonged plateau
      { duration: '30s', target: 0 },
    ],
    gracefulRampDown: '10s',
    tags: { test_phase: 'stress' },
  },
  spike: {
    executor: 'ramping-vus',
    startTime: '12m30s',
    startVUs: 0,
    stages: [
      { duration: '10s', target: 1500 }, // sudden surge
      { duration: '30s', target: 1500 },
      { duration: '10s', target: 0 },
    ],
    gracefulRampDown: '5s',
    tags: { test_phase: 'spike' },
  },
};

function selectScenarios() {
  if (!__ENV.SCENARIO) return allScenarios;
  const chosen = { ...allScenarios[__ENV.SCENARIO] };
  delete chosen.startTime;
  return { [__ENV.SCENARIO]: chosen };
}

export const options = {
  scenarios: selectScenarios(),
  // Client-side view of the SLOs. They are expected to fail during stress/spike: that is the incident.
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: ['p(95)<200'],
    'http_req_failed{test_phase:ramp_up}': ['rate<0.005'],
    'http_req_duration{test_phase:ramp_up}': ['p(95)<200'],
    'http_req_failed{test_phase:stress}': ['rate<0.005'],
    'http_req_duration{test_phase:stress}': ['p(95)<200'],
    'http_req_failed{test_phase:spike}': ['rate<0.005'],
    'http_req_duration{test_phase:spike}': ['p(95)<200'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const CARDS = ['4111111111111111', '5555555555554444', '4539148803436467'];

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

// Traffic mix of a typical shopping session.
export default function () {
  const r = Math.random();
  let res;
  if (r < 0.35) {
    res = http.get(`${BASE_URL}/api/v1/products`, { tags: { name: 'list_products' } });
  } else if (r < 0.55) {
    const id = Math.floor(Math.random() * 5) + 1; // id 5 does not exist -> 404 (client error)
    res = http.get(`${BASE_URL}/api/v1/products/${id}`, { tags: { name: 'get_product' } });
  } else if (r < 0.75) {
    const body = JSON.stringify({
      product_id: Math.floor(Math.random() * 3) + 1,
      quantity: Math.floor(Math.random() * 3) + 1,
      currency: pick(['EUR', 'USD', 'TND']),
      card_number: Math.random() < 0.05 ? '4111111111111112' : pick(CARDS),
    });
    res = http.post(`${BASE_URL}/api/v1/payments`, body, {
      headers: { 'Content-Type': 'application/json' },
      tags: { name: 'create_payment' },
    });
  } else if (r < 0.97) {
    res = http.get(`${BASE_URL}/checkout`, { tags: { name: 'checkout' } });
  } else {
    res = http.get(`${BASE_URL}/flaky`, { tags: { name: 'flaky' } });
  }
  check(res, { 'no server error (status < 500)': (x) => x.status < 500 });
  sleep(0.5 + Math.random()); // think time
}
