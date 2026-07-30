const { PrismaClient } = require('@prisma/client');
const { PrismaPg } = require('@prisma/adapter-pg');
const { createOrderSchema } = require('../validators/order.validator');
const { getProduct, decrementStock } = require('../clients/product.client');
const { chargePayment } = require('../clients/payment.client');
const logger = require('../utils/logger');

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter });

// POST /orders
exports.createOrder = async (req, res, next) => {
  const parsed = createOrderSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: parsed.error.issues });
  }
  const { userId, items } = parsed.data;

  try {
    const enrichedItems = [];
    for (const item of items) {
      let product;
      try {
        product = await getProduct(item.productId);
      } catch (err) {
        logger.warn('Product service call failed', { productId: item.productId, error: err.message });
        return res.status(502).json({ error: `Failed to fetch product ${item.productId}` });
      }

      if (product.stock < item.quantity) {
        return res.status(409).json({ error: `Insufficient stock for product ${item.productId}` });
      }

      enrichedItems.push({
        productId: item.productId,
        quantity: item.quantity,
        price: product.price,
      });
    }

    const totalAmount = enrichedItems.reduce(
      (sum, item) => sum + item.price * item.quantity,
      0
    );

    const order = await prisma.order.create({
      data: {
        userId,
        items: enrichedItems,
        totalAmount,
        status: 'pending',
      },
    });

    let payment;
    try {
      payment = await chargePayment({
        idempotencyKey: `order-${order.id}`,
        orderId: String(order.id),
        amount: totalAmount,
      });
    } catch (err) {
      logger.warn('Payment service unreachable', { orderId: order.id, error: err.message });
      const failed = await prisma.order.update({
        where: { id: order.id },
        data: { status: 'failed', failureReason: 'Payment service unreachable' },
      });
      return res.status(502).json(failed);
    }

    if (payment.status !== 'succeeded') {
      const failed = await prisma.order.update({
        where: { id: order.id },
        data: {
          status: 'failed',
          failureReason: payment.failureReason || 'Payment declined',
          paymentId: payment.id,
        },
      });
      logger.warn('Order failed due to payment decline', { orderId: order.id, paymentId: payment.id });
      return res.status(402).json(failed);
    }

    try {
      for (const item of enrichedItems) {
        await decrementStock(item.productId, item.quantity);
      }
    } catch (err) {
      logger.error('Stock decrement failed after successful payment', {
        orderId: order.id,
        error: err.message,
      });
    }

    const confirmed = await prisma.order.update({
      where: { id: order.id },
      data: { status: 'confirmed', paymentId: payment.id },
    });

    logger.info('Order confirmed', { orderId: confirmed.id, userId, totalAmount });
    res.status(201).json(confirmed);
  } catch (err) {
    next(err);
  }
};

// GET /orders/:id
exports.getOrder = async (req, res, next) => {
  try {
    const order = await prisma.order.findUnique({
      where: { id: parseInt(req.params.id) },
    });
    if (!order) return res.status(404).json({ error: 'Order not found' });
    res.json(order);
  } catch (err) {
    next(err);
  }
};