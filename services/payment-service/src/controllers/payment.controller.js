const { PrismaClient } = require('@prisma/client');
const { PrismaPg } = require('@prisma/adapter-pg');
const { chargeSchema } = require('../validators/payment.validator');
const logger = require('../utils/logger');

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter });

const FAILURE_RATE = parseFloat(process.env.PAYMENT_FAILURE_RATE || '0.05');
const DELAY_MS = parseInt(process.env.PAYMENT_DELAY_MS || '300');

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// POST /payments/charge
exports.charge = async (req, res, next) => {
  try {
    const parsed = chargeSchema.safeParse(req.body);
    if (!parsed.success) {
      return res.status(400).json({ error: parsed.error.issues });
    }
    const { idempotencyKey, orderId, amount } = parsed.data;

    const existing = await prisma.payment.findUnique({ where: { idempotencyKey } });
    if (existing) {
      logger.info('Duplicate payment request returned existing record', { idempotencyKey });
      return res.status(200).json(existing);
    }

    const payment = await prisma.payment.create({
      data: { idempotencyKey, orderId, amount, status: 'pending' },
    });

    await sleep(DELAY_MS);

    const didFail = Math.random() < FAILURE_RATE;

    const updated = await prisma.payment.update({
      where: { id: payment.id },
      data: didFail
        ? { status: 'failed', failureReason: 'Simulated payment decline' }
        : { status: 'succeeded' },
    });

    if (didFail) {
      logger.warn('Payment failed', { paymentId: payment.id, orderId, amount });
      return res.status(402).json(updated);
    }

    logger.info('Payment succeeded', { paymentId: payment.id, orderId, amount });
    res.status(201).json(updated);
  } catch (err) {
    next(err);
  }
};

// GET /payments/:id
exports.getPayment = async (req, res, next) => {
  try {
    const payment = await prisma.payment.findUnique({
      where: { id: parseInt(req.params.id) },
    });
    if (!payment) return res.status(404).json({ error: 'Payment not found' });
    res.json(payment);
  } catch (err) {
    next(err);
  }
};