# Jaeger

Distributed tracing backend. Collects OpenTelemetry spans from the
services and visualizes request flows across order → product → payment.

Runs via the `jaegertracing/all-in-one` image (see docker-compose.yml),
which uses in-memory storage and requires no config file for this setup.

- UI: http://localhost:16686
- OTLP receiver: port 4317 (gRPC), 4318 (HTTP)