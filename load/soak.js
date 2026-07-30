import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT, CART, ORDER, JSON_HEADERS, orderBody, cartItemBody } from './config.js';

// Soak test: moderate, STEADY load sustained for a long time.
// Purpose: reveal slow problems (memory leaks, connection exhaustion,
// gradual degradation) that only appear over extended runs.
// This also produces the long "normal baseline" the ML models train on.
export const options = {
  stages: [
    { duration: '1m',  target: 8 },   // ramp up to 8 users
    { duration: '30m', target: 8 },   // HOLD steady for 30 minutes
    { duration: '1m',  target: 0 },   // ramp down
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

  const viewCart = http.get(`${CART}/cart/${userId}`);
  check(viewCart, { 'cart viewed': (r) => r.status === 200 });
  sleep(1);

  const o = http.post(`${ORDER}/orders`, orderBody(), JSON_HEADERS);
  check(o, { 'order placed or declined': (r) => r.status === 201 || r.status === 402 });
  sleep(2);
}