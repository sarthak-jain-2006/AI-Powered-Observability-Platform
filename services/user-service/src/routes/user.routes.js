const express = require('express');
const router = express.Router();
const controller = require('../controllers/user.controller');
const verifyToken = require('../middleware/auth.middleware');

router.post('/signup', controller.signup);
router.post('/login', controller.login);
router.get('/me', verifyToken, controller.getMe);

module.exports = router;