import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT, CART, ORDER, JSON_HEADERS, orderBody, cartItemBody } from './config.js';

// Stress test: steadily increasing load beyond normal capacity,
// to find the breaking point. Degradation here = what the LSTM/TCN metric model detects.
export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '2m', target: 50 },
    { duration: '2m', target: 100 },
    { duration: '2m', target: 200 },   // push hard
    { duration: '2m', target: 0 },
  ],
};

export default function () {
  const userId = __VU;

  const p = http.get(`${PRODUCT}/products/3`);
  check(p, { 'product fetched': (r) => r.status === 200 });
  sleep(1);

  const addToCart = http.post(`${CART}/cart/${userId}/items`, cartItemBody(), JSON_HEADERS);
  check(addToCart, { 'added to cart': (r) => r.status === 201 });
  sleep(1);

  const o = http.post(`${ORDER}/orders`, orderBody(), JSON_HEADERS);
  check(o, { 'order ok': (r) => r.status === 201 || r.status === 402 });
  sleep(1);
}