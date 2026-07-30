const Redis = require('ioredis');
const { addItemSchema } = require('../validators/cart.validator');
const logger = require('../utils/logger');

const redis = new Redis({
  host: process.env.REDIS_HOST,
  port: process.env.REDIS_PORT,
});

// GET /cart/:userId
exports.getCart = async (req, res, next) => {
  try {
    const { userId } = req.params;
    const cartData = await redis.get(`cart:${userId}`);
    const cart = cartData ? JSON.parse(cartData) : { items: [] };
    res.json(cart);
  } catch (err) {
    next(err);
  }
};

// POST /cart/:userId/items
exports.addItem = async (req, res, next) => {
  try {
    const parsed = addItemSchema.safeParse(req.body);
    if (!parsed.success) {
      return res.status(400).json({ error: parsed.error.issues });
    }
    const { productId, quantity, price } = parsed.data;

    const { userId } = req.params;
    const cartData = await redis.get(`cart:${userId}`);
    const cart = cartData ? JSON.parse(cartData) : { items: [] };

    const existingItem = cart.items.find(item => item.productId === productId);
    if (existingItem) {
      existingItem.quantity += quantity;
    } else {
      cart.items.push({ productId, quantity, price });
    }

    await redis.set(`cart:${userId}`, JSON.stringify(cart));
    logger.info('Item added to cart', { userId, productId, quantity });
    res.status(201).json(cart);
  } catch (err) {
    next(err);
  }
};

// DELETE /cart/:userId/items/:productId
exports.removeItem = async (req, res, next) => {
  try {
    const { userId, productId } = req.params;

    const cartData = await redis.get(`cart:${userId}`);
    if (!cartData) return res.json({ items: [] });

    const cart = JSON.parse(cartData);
    cart.items = cart.items.filter(item => item.productId !== productId);

    await redis.set(`cart:${userId}`, JSON.stringify(cart));
    res.json(cart);
  } catch (err) {
    next(err);
  }
};

// DELETE /cart/:userId
exports.clearCart = async (req, res, next) => {
  try {
    const { userId } = req.params;
    await redis.del(`cart:${userId}`);
    res.status(204).send();
  } catch (err) {
    next(err);
  }
};