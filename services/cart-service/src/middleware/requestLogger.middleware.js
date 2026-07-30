const logger = require('../utils/logger');
const { httpRequestCounter, httpRequestDuration } = require('../utils/metrics');

module.exports = function requestLogger(req, res, next) {
  const start = Date.now();

  res.on('finish', () => {
    const durationMs = Date.now() - start;
    const route = req.route ? req.baseUrl + req.route.path : req.originalUrl;

    logger.info('Request handled', {
      method: req.method,
      path: req.originalUrl,
      statusCode: res.statusCode,
      durationMs,
    });

    httpRequestCounter.inc({
      method: req.method,
      route,
      status_code: res.statusCode,
    });

    httpRequestDuration.observe(
      { method: req.method, route, status_code: res.statusCode },
      durationMs / 1000
    );
  });

  next();
};