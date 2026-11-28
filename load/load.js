// k6 load profile for the demo app.
// NOTE: env vars are LOAD_* not K6_* on purpose: k6 treats K6_DURATION etc. as its own CLI options,
// which would override the scenario below.
// Constant-arrival-rate with a slow sine "wave" so the baseline is not perfectly flat
// (gives PCA a realistic "load goes up, everything goes up" direction to learn).
import http from 'k6/http';
import { check } from 'k6';

const TARGET = __ENV.TARGET || 'http://localhost:8000';
const DURATION = __ENV.LOAD_DURATION || '10m';
const RPS = parseInt(__ENV.LOAD_RPS || '20', 10);
const WAVE = parseFloat(__ENV.LOAD_WAVE_PERIOD_S || '300');
const DEFAULT_TIMEOUT = '60s';

// The long scenario publishes client_retries and timeout_ms on GET /fault.
// Each VU caches that snapshot for a few seconds. /fault is not part of the RED metrics.
let faultCache = { client_retries: 0, timeout_ms: 0 };
let faultFetchedAt = 0;

function currentFaults() {
  const now = Date.now();
  if (now - faultFetchedAt < 5000) return faultCache;
  faultFetchedAt = now;
  const res = http.get(`${TARGET}/fault`, { tags: { name: 'fault-state' }, timeout: '2s' });
  if (res.status === 200) {
    try {
      const body = res.json();
      faultCache = {
        client_retries: Number(body.client_retries || 0),
        timeout_ms: Number(body.timeout_ms || 0),
      };
    } catch (_err) {
      // Keep the previous snapshot. A bad read should not stop the load.
    }
  }
  return faultCache;
}

function requestTimeout(faults) {
  // Wait slightly longer than the server budget so the 504 is recorded, instead of a client abort.
  if (faults.timeout_ms > 0) return `${Math.round(faults.timeout_ms + 500)}ms`;
  return DEFAULT_TIMEOUT;
}

function send(url, name, timeout) {
  return http.get(url, { tags: { name }, timeout });
}

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: RPS * 2,            // upper bound; we thin requests below to shape the wave
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: 20,
      maxVUs: 200,
    },
  },
  thresholds: {},             // no pass/fail - this is a lab, faults are expected
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

const start = Date.now();

export default function () {
  const t = (Date.now() - start) / 1000;
  // keep probability in [0.25, 0.75] -> effective rate oscillates between 0.5x and 1.5x RPS
  const keep = 0.5 + 0.25 * Math.sin((2 * Math.PI * t) / WAVE);
  if (Math.random() > keep) return;

  const faults = currentFaults();
  const timeout = requestTimeout(faults);
  const r = Math.random();
  let url;
  let name;
  if (r < 0.7) {
    name = 'items';
    url = `${TARGET}/api/items`;
  } else {
    name = 'work';
    const n = 1000 + Math.floor(Math.random() * 3000);
    url = `${TARGET}/api/work?n=${n}`;
  }
  let res = send(url, name, timeout);
  const extra = Math.max(0, Math.min(2, faults.client_retries || 0));
  for (let i = 0; i < extra && (res.status === 0 || res.status >= 500); i++) {
    res = send(url, name, timeout);
  }
  check(res, { 'status is 2xx': (x) => x.status >= 200 && x.status < 300 });
}
