# Central config for the AI engine.

import os

# Data source URLs — service names, since this runs inside the compose network
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
JAEGER_URL = os.getenv("JAEGER_URL", "http://jaeger:16686")

# How often to collect a snapshot (seconds).
# 10s so short faults land in more than one sample — the cpu-stress burst used
# to be shorter than a single 30s interval and could slip between samples.
COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "10"))

# Lookback window for the rate()/count_over_time() queries.
# Kept at 1m to match the Prometheus recording window.
LOOKBACK = "1m"

# The services we monitor
SERVICES = [
    "product-service",
    "user-service",
    "cart-service",
    "payment-service",
    "order-service",
]

# Where snapshots are written
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "snapshots.jsonl")

# Ground-truth fault labels, written by the fault runner (faults/run-fault.ps1).
FAULT_EVENTS_FILE = os.path.join(DATA_DIR, "fault_events.jsonl")
