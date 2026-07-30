import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT } from './config.js';

// Read-heavy scenario: hammer product lookups. Isolates product-service.
export const options = {
  stages: [
    { duration: '30s', target: 20 },
    { duration: '1m',  target: 20 },
    { duration: '30s', target: 0 },
  ],
};

export default function () {
  const p = http.get(`${PRODUCT}/products/3`);
  check(p, { 'product fetched': (r) => r.status === 200 });
  sleep(0.5);
}