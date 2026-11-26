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

  const r = Math.random();
  let res;
  if (r < 0.7) {
    res = http.get(`${TARGET}/api/items`, { tags: { name: 'items' } });
  } else {
    const n = 1000 + Math.floor(Math.random() * 3000);
    res = http.get(`${TARGET}/api/work?n=${n}`, { tags: { name: 'work' } });
  }
  check(res, { 'status is 2xx': (x) => x.status >= 200 && x.status < 300 });
}
