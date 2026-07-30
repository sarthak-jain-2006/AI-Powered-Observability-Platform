const express = require('express');
const userRoutes = require('./routes/user.routes');
const requestLogger = require('./middleware/requestLogger.middleware');
const errorHandler = require('./middleware/errorHandler.middleware');
const { register } = require('./utils/metrics');
const { router: faultRouter, faultMiddleware } = require('./faultInjector');  // ADD

const app = express();
app.use(express.json());
app.use(requestLogger);

app.use(faultMiddleware);              // ADD — applies faults to real traffic
app.use('/admin', faultRouter);        // ADD — exposes /admin/inject/* controls
app.get('/health', (req, res) => res.json({ status: 'ok' }));
app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

app.use('/users', userRoutes);

app.use(errorHandler);

module.exports = app;