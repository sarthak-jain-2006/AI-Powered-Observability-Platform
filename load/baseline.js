import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT, CART, ORDER, USER, JSON_HEADERS, orderBody, cartItemBody, signupBody } from './config.js';

// Long unattended run that produces the "normal" dataset the Isolation Forest
// is fitted on.
//
// The load deliberately cycles between levels instead of holding flat. A model
// trained on a single constant request rate learns "normal = exactly this much
// traffic", and then flags every ordinary load change as an anomaly. Cycling
// teaches it that load varies on its own, which forces the features to carry
// the relationship between request rate and latency rather than the absolute
// latency value. That relationship is the whole point of collecting a baseline.
//
// Usage:
//   docker compose run -d --rm k6 run /scripts/baseline.js
//   docker compose run -d --rm -e BASELINE_HOURS=8 --rm k6 run /scripts/baseline.js

const HOURS = parseFloat(__ENV.BASELINE_HOURS || '6');
const HOLD_MINUTES = parseFloat(__ENV.HOLD_MINUTES || '10');
const LEVELS = (__ENV.LEVELS || '3,6,10,15').split(',').map(Number);

const RAMP_MINUTES = 0.5;
const cycleMinutes = LEVELS.length * (RAMP_MINUTES + HOLD_MINUTES);
const cycles = Math.max(1, Math.ceil((HOURS * 60) / cycleMinutes));

function buildStages() {
  const stages = [];
  for (let c = 0; c < cycles; c++) {
    for (const target of LEVELS) {
      stages.push({ duration: `${RAMP_MINUTES * 60}s`, target });
      stages.push({ duration: `${HOLD_MINUTES}m`, target });
    }
  }
  return stages;
}

export const options = {
  stages: buildStages(),
  // A declined payment is a normal business outcome here, not a failed run.
  thresholds: {},
};

export function setup() {
  console.log(
    `baseline: ${cycles} cycles x ${cycleMinutes}min over levels [${LEVELS}] ` +
    `= ~${((cycles * cycleMinutes) / 60).toFixed(1)}h`
  );
}

export default function () {
  const userId = __VU;

  // Occasional signup so user-service has a baseline of its own.
  if (Math.random() < 0.2) {
    const s = http.post(`${USER}/users/signup`, signupBody(), JSON_HEADERS);
    check(s, { 'signed up': (r) => r.status === 201 || r.status === 409 });
    sleep(1);
  }

  const p = http.get(`${PRODUCT}/products/3`);
  check(p, { 'product fetched': (r) => r.status === 200 });
  sleep(1);

  const addToCart = http.post(`${CART}/cart/${userId}/items`, cartItemBody(), JSON_HEADERS);
  check(addToCart, { 'added to cart': (r) => r.status === 201 });
  sleep(1);

  const viewCart = http.get(`${CART}/cart/${userId}`);
  check(viewCart, { 'cart viewed': (r) => r.status === 200 });
  sleep(1);

  // 402 is an ordinary decline (PAYMENT_FAILURE_RATE), not an error.
  const o = http.post(`${ORDER}/orders`, orderBody(), JSON_HEADERS);
  check(o, { 'order placed or declined': (r) => r.status === 201 || r.status === 402 });
  sleep(1);
}
