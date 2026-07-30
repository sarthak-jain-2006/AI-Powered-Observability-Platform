export const PRODUCT = 'http://product-service:3001';
export const USER    = 'http://user-service:3002';
export const CART    = 'http://cart-service:3003';
export const PAYMENT = 'http://payment-service:3004';
export const ORDER   = 'http://order-service:3005';

export const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };

// Order body — matches order validator (userId=number, productId=string)
export function orderBody(productId = '3', quantity = 1, userId = 1) {
  return JSON.stringify({ userId, items: [{ productId, quantity }] });
}

// Cart add-item body — matches cart validator (productId, quantity, price)
export function cartItemBody(productId = '3', quantity = 1, price = 50) {
  return JSON.stringify({ productId, quantity, price });
}

// Signup body — unique email each call
export function signupBody() {
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return JSON.stringify({
    email: `loadtest-${unique}@test.com`,
    password: 'password123',
    name: 'Load Test User',
  });
}