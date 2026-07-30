import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT, CART, ORDER, JSON_HEADERS, orderBody, cartItemBody } from './config.js';

// Spike test: normal load, then a SUDDEN sharp surge, then back to normal.
// This is an anomaly generator — the abrupt jump is what anomaly detection must catch.
export const options = {
  stages: [
    { duration: '1m',  target: 5 },    // normal baseline
    { duration: '10s', target: 100 },  // SUDDEN spike to 100 users
    { duration: '30s', target: 100 },  // hold the spike briefly
    { duration: '10s', target: 5 },    // drop back to normal
    { duration: '1m',  target: 5 },    // recover
    { duration: '10s', target: 0 },
  ],
};

export default function () {
  const userId = __VU;

  const p = http.get(`${PRODUCT}/products/3`);
  check(p, { 'product fetched': (r) => r.status === 200 });
  sleep(1);

  const o = http.post(`${ORDER}/orders`, orderBody(), JSON_HEADERS);
  check(o, { 'order ok': (r) => r.status === 201 || r.status === 402 });
  sleep(1);
}