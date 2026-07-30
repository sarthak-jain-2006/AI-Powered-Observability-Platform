import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT, USER, CART, ORDER, JSON_HEADERS, orderBody, cartItemBody, signupBody } from './config.js';

export const options = {
  vus: 1,
  duration: '30s',
};

export default function () {
  const userId = 1;

  // 1. Browse a product
  const p = http.get(`${PRODUCT}/products/3`);
  check(p, { 'GET product is 200': (r) => r.status === 200 });
  sleep(1);

  // 2. Add item to cart
  const addToCart = http.post(`${CART}/cart/${userId}/items`, cartItemBody(), JSON_HEADERS);
  check(addToCart, { 'POST add to cart is 201': (r) => r.status === 201 });
  sleep(1);

  // 3. View cart
  const viewCart = http.get(`${CART}/cart/${userId}`);
  check(viewCart, { 'GET cart is 200': (r) => r.status === 200 });
  sleep(1);

  // 4. Place order (order -> product -> payment)
  const o = http.post(`${ORDER}/orders`, orderBody(), JSON_HEADERS);
  check(o, { 'POST order is 201 or 402': (r) => r.status === 201 || r.status === 402 });
  sleep(1);

  // 5. Sign up a user
  const s = http.post(`${USER}/users/signup`, signupBody(), JSON_HEADERS);
  check(s, { 'POST signup is 201': (r) => r.status === 201 });
  sleep(1);
}