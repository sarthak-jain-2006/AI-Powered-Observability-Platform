const winston = require('winston');
const { trace } = require('@opentelemetry/api');

// Stamp the active span's ids onto every record. The Grafana Loki datasource
// derives a trace link from the trace_id field, so without this the log -> trace
// jump silently never matches.
const traceContext = winston.format((info) => {
  const span = trace.getActiveSpan();
  if (span) {
    const { traceId, spanId } = span.spanContext();
    info.trace_id = traceId;
    info.span_id = spanId;
  }
  return info;
});

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    traceContext(),
    winston.format.timestamp(),
    winston.format.json()
  ),
  defaultMeta: { service: 'user-service' },
  transports: [
    new winston.transports.Console(),
  ],
});

module.exports = logger;
