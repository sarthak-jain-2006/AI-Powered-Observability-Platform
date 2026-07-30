const { z } = require('zod');

const createOrderSchema = z.object({
  userId: z.number().int().positive(),
  items: z.array(
    z.object({
      productId: z.string().min(1),
      quantity: z.number().int().positive(),
    })
  ).min(1, 'Order must have at least one item'),
});

module.exports = { createOrderSchema };