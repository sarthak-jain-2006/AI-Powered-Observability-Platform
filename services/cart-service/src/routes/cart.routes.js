const express = require('express');
const router = express.Router();
const controller = require('../controllers/cart.controller');

router.get('/:userId', controller.getCart);
router.post('/:userId/items', controller.addItem);
router.delete('/:userId/items/:productId', controller.removeItem);
router.delete('/:userId', controller.clearCart);

module.exports = router;