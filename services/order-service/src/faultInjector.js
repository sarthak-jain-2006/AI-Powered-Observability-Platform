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
  leakTimer: null,    // interval driving a gradual leak, so reset can stop it
  cpuUntil: 0,        // epoch ms the CPU burn should stop; reset sets it to 0
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

// CPU stress:  POST /admin/inject/cpu  { "seconds": 180, "intensity": 0.4 }
//
// `intensity` is the duty cycle: the fraction of each 50ms slice spent spinning
// rather than yielding. Without it every CPU fault is full-throttle, which
// makes the fault trivially detectable and leaves no subtle variant to test
// against. 1.0 reproduces the original behaviour.
router.post('/inject/cpu', express.json(), (req, res) => {
  const seconds = parseInt(req.body.seconds) || 5;
  const raw = req.body.intensity === undefined ? 1 : parseFloat(req.body.intensity);
  const intensity = Math.min(1, Math.max(0.05, isNaN(raw) ? 1 : raw));

  res.json({ injected: 'cpu', seconds, intensity });   // respond BEFORE burning

  const SLICE_MS = 50;
  const spinMs = Math.max(1, Math.round(SLICE_MS * intensity));
  const restMs = SLICE_MS - spinMs;

  faultState.cpuUntil = Date.now() + seconds * 1000;

  function burn() {
    // Read the deadline from state rather than closing over it, so /reset can
    // stop an in-flight burn by zeroing it.
    if (Date.now() >= faultState.cpuUntil) {
      faultState.cpuUntil = 0;
      return;
    }
    const spinUntil = Date.now() + spinMs;
    while (Date.now() < spinUntil) { Math.sqrt(Math.random()); }
    // Resting via setTimeout leaves the event loop genuinely idle between
    // slices; setImmediate would re-enter at once and pin the core regardless
    // of the requested intensity.
    if (restMs > 0) setTimeout(burn, restMs);
    else setImmediate(burn);
  }
  burn();
});

// Memory leak:  POST /admin/inject/memory  { "mb": 200, "overSeconds": 600 }
//
// With `overSeconds` the memory is allocated incrementally instead of all at
// once. That difference matters: a single allocation is a step change that any
// threshold catches, whereas a real leak is slow drift whose current reading
// looks unremarkable and only its trend gives away. Drift is the case the
// long-horizon slope features exist to detect, so it needs a fault that
// actually produces it. Omitting overSeconds keeps the original one-shot
// behaviour.
router.post('/inject/memory', express.json(), (req, res) => {
  const mb = parseInt(req.body.mb) || 50;
  const overSeconds = parseInt(req.body.overSeconds) || 0;

  const allocate = (count) => {
    for (let i = 0; i < count; i++) {
      faultState.memoryLeak.push(Buffer.alloc(1024 * 1024, 1)); // 1 MB, held forever
    }
  };

  if (faultState.leakTimer) {
    clearInterval(faultState.leakTimer);
    faultState.leakTimer = null;
  }

  if (overSeconds <= 0) {
    allocate(mb);
    return res.json({
      injected: 'memory', mode: 'immediate', mb,
      totalLeakedMb: faultState.memoryLeak.length,
    });
  }

  res.json({ injected: 'memory', mode: 'gradual', mb, overSeconds });

  const TICK_MS = 1000;
  const ticks = Math.max(1, Math.round((overSeconds * 1000) / TICK_MS));
  const startedAt = Date.now();
  const startingMb = faultState.memoryLeak.length;

  faultState.leakTimer = setInterval(() => {
    // Derive the target from elapsed time rather than accumulating per tick, so
    // a delayed or skipped timer does not permanently shrink the leak.
    const elapsed = (Date.now() - startedAt) / (overSeconds * 1000);
    const target = startingMb + Math.min(mb, Math.round(mb * Math.min(1, elapsed)));
    const shortfall = target - faultState.memoryLeak.length;
    if (shortfall > 0) allocate(shortfall);

    if (faultState.memoryLeak.length >= startingMb + mb) {
      clearInterval(faultState.leakTimer);
      faultState.leakTimer = null;
    }
  }, TICK_MS);
});

// Reset all faults:  POST /admin/inject/reset
router.post('/inject/reset', (req, res) => {
  faultState.errorRate = 0;
  faultState.extraDelayMs = 0;
  // Stop a gradual leak still in progress, or it keeps allocating after recovery
  // and the next episode starts from a dirty baseline.
  if (faultState.leakTimer) {
    clearInterval(faultState.leakTimer);
    faultState.leakTimer = null;
  }
  faultState.cpuUntil = 0;          // stops any in-flight CPU burn
  faultState.memoryLeak = [];       // drop references → GC reclaims the leaked memory
  res.json({ reset: true });
});

// Status:  GET /admin/inject/status
router.get('/inject/status', (req, res) => {
  res.json({
    errorRate: faultState.errorRate,
    extraDelayMs: faultState.extraDelayMs,
    leakedMb: faultState.memoryLeak.length,
    leaking: Boolean(faultState.leakTimer),
    cpuBurning: faultState.cpuUntil > Date.now(),
  });
});

module.exports = { router, faultMiddleware };
