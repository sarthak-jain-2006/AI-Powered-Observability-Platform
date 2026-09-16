import http from 'k6/http';
import { check, sleep } from 'k6';
import { PRODUCT, CART, ORDER, USER, JSON_HEADERS, orderBody, cartItemBody, signupBody } from './config.js';

// Full shopping journey under steady load:
// browse -> add to cart -> view cart -> checkout.
export const options = {
  stages: [
    { duration: '30s', target: 10 },  // ramp up to 10 users
    { duration: '2m',  target: 10 },  // hold steady (the baseline)
    { duration: '30s', target: 0 },   // ramp down
  ],
};

export default function () {
  // Each virtual user gets a distinct userId so their carts don't collide
  const userId = __VU;

  // Sign up occasionally. Without this user-service receives no traffic at all
  // and has no baseline behaviour to learn -- it was flat zero in every
  // snapshot collected so far. Kept to a fraction of iterations so signups stay
  // a minority of the mix, the way they are in a real storefront.
  if (Math.random() < 0.2) {
    const s = http.post(`${USER}/users/signup`, signupBody(), JSON_HEADERS);
    check(s, { 'signed up': (r) => r.status === 201 || r.status === 409 });
    sleep(1);
  }

  // Browse
  const p = http.get(`${PRODUCT}/products/3`);
  check(p, { 'product fetched': (r) => r.status === 200 });
  sleep(1);

  // Add to cart
  const addToCart = http.post(`${CART}/cart/${userId}/items`, cartItemBody(), JSON_HEADERS);
  check(addToCart, { 'added to cart': (r) => r.status === 201 });
  sleep(1);

  // View cart
  const viewCart = http.get(`${CART}/cart/${userId}`);
  check(viewCart, { 'cart viewed': (r) => r.status === 200 });
  sleep(1);

  // Checkout (order -> product -> payment)
  const o = http.post(`${ORDER}/orders`, orderBody(), JSON_HEADERS);
  check(o, { 'order placed or declined': (r) => r.status === 201 || r.status === 402 });
  sleep(1);
}