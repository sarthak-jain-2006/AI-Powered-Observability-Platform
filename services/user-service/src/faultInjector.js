// faultInjector.js
// Injectable fault module — mounted into a service to allow runtime fault injection.
// State is in-memory, so faults toggle live with NO container restart.
// Exposes /admin/inject/* endpoints and a middleware that applies active faults.

const express = require('express');
const router = express.Router();

// Fault state for THIS service instance. Starts clean (no faults).
const faultState = {
  errorRate: 0,       // 0.0–1.0: fraction of requests to fail with HTTP 500
  extraDelayMs: 0,    // artificial latency added to each request (ms)
  memoryLeak: [],     // holds allocated buffers so GC cannot reclaim them
};

// --- Middleware: applied to every incoming request, injects active faults ---
function faultMiddleware(req, res, next) {
  // Never fault the admin/observability endpoints themselves
  if (req.path.startsWith('/admin') || req.path === '/metrics' || req.path === '/health') {
    return next();
  }

  // Fault: latency — delay the request, then continue
  if (faultState.extraDelayMs > 0) {
    return setTimeout(() => maybeError(req, res, next), faultState.extraDelayMs);
  }
  return maybeError(req, res, next);
}

// Fault: error rate — probabilistically fail the request with a 500
function maybeError(req, res, next) {
  if (faultState.errorRate > 0 && Math.random() < faultState.errorRate) {
    return res.status(500).json({ error: 'Injected fault: simulated internal error' });
  }
  next();
}

// --- Control endpoints (how the runner triggers faults) ---

// Set error rate:  POST /admin/inject/error-rate  { "rate": 0.3 }
router.post('/inject/error-rate', express.json(), (req, res) => {
  const rate = parseFloat(req.body.rate);
  if (isNaN(rate) || rate < 0 || rate > 1) {
    return res.status(400).json({ error: 'rate must be between 0 and 1' });
  }
  faultState.errorRate = rate;
  res.json({ injected: 'error-rate', rate });
});

// Set latency:  POST /admin/inject/delay  { "ms": 3000 }
router.post('/inject/delay', express.json(), (req, res) => {
  const ms = parseInt(req.body.ms);
  if (isNaN(ms) || ms < 0) {
    return res.status(400).json({ error: 'ms must be >= 0' });
  }
  faultState.extraDelayMs = ms;
  res.json({ injected: 'delay', ms });
});

// CPU stress:  POST /admin/inject/cpu  { "seconds": 10 }
// Burns CPU with busy work for the duration (spikes CPU usage).
router.post('/inject/cpu', express.json(), (req, res) => {
  const seconds = parseInt(req.body.seconds) || 5;
  res.json({ injected: 'cpu', seconds });   // respond BEFORE burning
  const end = Date.now() + seconds * 1000;
  function burn() {
    const spinUntil = Date.now() + 50;             // spin 50ms
    while (Date.now() < spinUntil) { Math.sqrt(Math.random()); }
    if (Date.now() < end) setImmediate(burn);      // yield, then continue
  }
  burn();
});

// Memory leak:  POST /admin/inject/memory  { "mb": 100 }
// Allocates and RETAINS memory (never freed) to simulate a leak.
router.post('/inject/memory', express.json(), (req, res) => {
  const mb = parseInt(req.body.mb) || 50;
  for (let i = 0; i < mb; i++) {
    faultState.memoryLeak.push(Buffer.alloc(1024 * 1024, 1)); // 1 MB each, held forever
  }
  res.json({ injected: 'memory', mb, totalLeakedMb: faultState.memoryLeak.length });
});

// Reset all faults:  POST /admin/inject/reset
router.post('/inject/reset', (req, res) => {
  faultState.errorRate = 0;
  faultState.extraDelayMs = 0;
  faultState.memoryLeak = [];   // drop references → GC reclaims the leaked memory
  res.json({ reset: true });
});

// Status:  GET /admin/inject/status
router.get('/inject/status', (req, res) => {
  res.json({
    errorRate: faultState.errorRate,
    extraDelayMs: faultState.extraDelayMs,
    leakedMb: faultState.memoryLeak.length,
  });
});

module.exports = { router, faultMiddleware };