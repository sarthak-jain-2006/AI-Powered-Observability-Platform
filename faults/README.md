# Fault Injection Suite

Controlled, reversible fault injection for testing observability and AI-based
anomaly detection. Each fault is a declarative JSON in `definitions/`, executed
via `run-fault.ps1`.

## Usage

    .\run-fault.ps1 -List                          # list all faults
    .\run-fault.ps1 -Fault <name> -Action inject   # trigger a fault
    .\run-fault.ps1 -Fault <name> -Action recover  # undo it

## Catalog

| Fault | Category | Type | Detection Signal |
|-------|----------|------|------------------|
| payment-failure | application | app | 5xx error_rate spike on payment-service |
| payment-delay | application | app | p95 latency spike on payment-service |
| db-down | database | infra | error_rate spike on product + order |
| db-delay | database | app | p95 latency spike on product-service |
| redis-down | infrastructure | infra | error_rate spike on cart-service |
| service-crash | infrastructure | infra | up==0 for payment-service; order 5xx |
| cpu-stress | resource | app | latency spike + CPU-bound on order-service |
| memory-leak | resource | app | RSS climbs without recovery on order-service |

## App faults vs infra faults

- **app** faults call `/admin/inject/*` endpoints inside the service (live, no restart)
- **infra** faults stop/start containers via Docker