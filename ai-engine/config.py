# Central config for the AI engine.

# Data source URLs — service names, since this runs inside the compose network
PROMETHEUS_URL = "http://prometheus:9090"
LOKI_URL = "http://loki:3100"
JAEGER_URL = "http://jaeger:16686"

# How often to collect a snapshot (seconds)
COLLECT_INTERVAL = 30

# The services we monitor
SERVICES = [
    "product-service",
    "user-service",
    "cart-service",
    "payment-service",
    "order-service",
]

# Where snapshots are written
SNAPSHOT_FILE = "/app/data/snapshots.jsonl"