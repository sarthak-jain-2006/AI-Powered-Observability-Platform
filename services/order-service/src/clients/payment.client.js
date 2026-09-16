const axios = require('axios');

const PAYMENT_SERVICE_URL = process.env.PAYMENT_SERVICE_URL;

async function chargePayment({ idempotencyKey, orderId, amount }) {
  const response = await axios.post(
    `${PAYMENT_SERVICE_URL}/payments/charge`,
    { idempotencyKey, orderId, amount },
    {
      timeout: 5000,
      // A 402 decline is a business outcome, not a transport failure. Without
      // this, axios throws on it and the caller cannot tell a declined card
      // apart from an unreachable payment service.
      validateStatus: (status) => status < 500,
    }
  );
  return response.data;
}

module.exports = { chargePayment };
