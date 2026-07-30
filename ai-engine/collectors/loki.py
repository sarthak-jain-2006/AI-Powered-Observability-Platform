import requests
from datetime import datetime, timezone, timedelta
from config import LOKI_URL, SERVICES
from utils.logger import get_logger

log = get_logger("loki")

def _query_range(logql, minutes=1):
    """Run a LogQL range query over the last N minutes. Returns result series."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    try:
        resp = requests.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": int(start.timestamp() * 1e9),  # Loki wants nanoseconds
                "end": int(end.timestamp() * 1e9),
                "step": f"{minutes}m",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            return []
        return data["data"]["result"]
    except Exception as e:
        log.error(f"Loki query error: {e}")
        return []

def collect_logs():
    """Count problem logs (warn + error) per service in the last minute.
    Returns { service: {error_log_count, warn_log_count, problem_log_count} }."""

    result = {svc: {"error_log_count": 0, "warn_log_count": 0, "problem_log_count": 0} for svc in SERVICES}

    for svc in SERVICES:
        err_res = _query_range(
            f'count_over_time({{compose_service="{svc}"}} | json | level=~"error" [1m])'
        )
        warn_res = _query_range(
            f'count_over_time({{compose_service="{svc}"}} | json | level=~"warn" [1m])'
        )
        errors = _sum_values(err_res)
        warns = _sum_values(warn_res)
        result[svc]["error_log_count"] = errors
        result[svc]["warn_log_count"] = warns
        result[svc]["problem_log_count"] = errors + warns   # the combined signal

    return result

def _sum_values(result):
    """Sum all values across returned series."""
    total = 0
    for series in result:
        for _, val in series.get("values", []):
            try:
                total += float(val)
            except ValueError:
                pass
    return int(total)


if __name__ == "__main__":
    import json
    print(json.dumps(collect_logs(), indent=2))