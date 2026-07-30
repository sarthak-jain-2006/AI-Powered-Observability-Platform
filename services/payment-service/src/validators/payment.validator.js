const { z } = require('zod');

const chargeSchema = z.object({
  idempotencyKey: z.string().min(1, 'idempotencyKey is required'),
  orderId: z.string().min(1, 'orderId is required'),
  amount: z.number().positive('amount must be a positive number'),
});

module.exports = { chargeSchema };