import requests
import math
from config import PROMETHEUS_URL, SERVICES
from utils.logger import get_logger

log = get_logger("prometheus")

def _query(promql):
    """Run a PromQL instant query, return the result vector."""
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            log.warning(f"Query failed: {promql}")
            return []
        return data["data"]["result"]
    except Exception as e:
        log.error(f"Prometheus query error: {e}")
        return []

def _to_map(result, label="job"):
    """Turn a Prometheus result vector into { service: value }. Skips NaN."""
    out = {}
    for series in result:
        svc = series["metric"].get(label)
        if svc:
            try:
                val = float(series["value"][1])
                if math.isnan(val):   # no-traffic division → treat as 0
                    val = 0.0
                out[svc] = val
            except (ValueError, IndexError):
                pass
    return out

def collect_metrics():
    """Collect key metrics per service. Returns { service: {metric: value} }."""

    # Error rate (5xx ratio) per service
    error_rate = _to_map(_query(
        'sum(rate(http_requests_total{status_code=~"5..", route!="/metrics"}[1m])) by (job) '
        '/ sum(rate(http_requests_total{route!="/metrics"}[1m])) by (job)'
    ))

    # p95 latency per service
    p95 = _to_map(_query(
        'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{route!="/metrics"}[1m])) by (le, job))'
    ))

    # Request rate per service
    req_rate = _to_map(_query(
        'sum(rate(http_requests_total{route!="/metrics"}[1m])) by (job)'
    ))

    # Memory (RSS bytes -> MB) per service
    memory = _to_map(_query('process_resident_memory_bytes'))

    # Service up/down
    up = _to_map(_query('up'))

    # Assemble per-service metric dicts
    metrics = {}
    for svc in SERVICES:
        metrics[svc] = {
            "error_rate": round(error_rate.get(svc, 0.0), 4),
            "p95_latency": round(p95.get(svc, 0.0), 4),
            "request_rate": round(req_rate.get(svc, 0.0), 4),
            "memory_mb": round(memory.get(svc, 0.0) / (1024 * 1024), 2),
            "up": int(up.get(svc, 0)),
        }
    return metrics