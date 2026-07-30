const { z } = require('zod');

const addItemSchema = z.object({
  productId: z.string().min(1, 'productId is required'),
  quantity: z.number().int().positive('quantity must be a positive integer'),
  price: z.number().positive('price must be a positive number'),
});

module.exports = { addItemSchema };