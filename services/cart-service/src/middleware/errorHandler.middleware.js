const logger = require('../utils/logger');

module.exports = function errorHandler(err, req, res, next) {
  logger.error('Unhandled error', {
    method: req.method,
    path: req.originalUrl,
    errorMessage: err.message,
    stack: err.stack,
  });

  res.status(err.statusCode || 500).json({
    error: err.message || 'Internal server error',
  });
};