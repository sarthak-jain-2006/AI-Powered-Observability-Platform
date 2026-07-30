const express = require('express');
const router = express.Router();
const controller = require('../controllers/product.controller');

router.get('/', controller.getAllProducts);
router.get('/:id', controller.getProductById);
router.post('/', controller.createProduct);
router.put('/:id', controller.updateProduct);
router.delete('/:id', controller.deleteProduct);
router.patch('/:id/decrement-stock', controller.decrementStock);

module.exports = router;