const client = require('prom-client');

// Collect default Node.js metrics (memory, CPU, event loop lag, etc.)
const register = new client.Registry();
client.collectDefaultMetrics({ register });

// Custom metric: count total HTTP requests, labeled by method/route/status
const httpRequestCounter = new client.Counter({
  name: 'http_requests_total',
  help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register],
});

// Custom metric: track request duration
const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5],
  registers: [register],
});

module.exports = { register, httpRequestCounter, httpRequestDuration };