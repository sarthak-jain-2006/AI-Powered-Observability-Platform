const axios = require('axios');

const PAYMENT_SERVICE_URL = process.env.PAYMENT_SERVICE_URL;

async function chargePayment({ idempotencyKey, orderId, amount }) {
  const response = await axios.post(
    `${PAYMENT_SERVICE_URL}/payments/charge`,
    { idempotencyKey, orderId, amount },
    { timeout: 5000 }
  );
  return response.data;
}

module.exports = { chargePayment };