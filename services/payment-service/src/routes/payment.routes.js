const express = require('express');
const router = express.Router();
const controller = require('../controllers/payment.controller');

router.post('/charge', controller.charge);
router.get('/:id', controller.getPayment);

module.exports = router;