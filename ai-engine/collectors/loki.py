import requests
from config import LOKI_URL, SERVICES, LOOKBACK
from utils.logger import get_logger

log = get_logger("loki")

# Regex alternation of every monitored service, so one query covers them all
# instead of one request per service per level.
_SVC_RE = "|".join(SERVICES)


def _query(logql):
    """Run an instant LogQL query. Returns the result vector.

    Deliberately the instant endpoint, not query_range: count_over_time([1m])
    sampled at a 1m step returns overlapping windows, and summing those points
    counts the same log lines more than once.
    """
    try:
        resp = requests.get(
            f"{LOKI_URL}/loki/api/v1/query",
            params={"query": logql},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            log.warning(f"Loki query failed: {logql}")
            return []
        return data["data"]["result"]
    except Exception as e:
        log.error(f"Loki query error: {e}")
        return []


def collect_logs():
    """Log-derived features per service over the last lookback window.

    Returns { service: {error_log_count, warn_log_count, problem_log_count,
                        total_log_count} }
    """
    result = {
        svc: {
            "error_log_count": 0,
            "warn_log_count": 0,
            "problem_log_count": 0,
            "total_log_count": 0,
        }
        for svc in SERVICES
    }

    # Counts split by level. __error__="" drops lines that aren't JSON (node and
    # express emit a few plain-text startup lines) rather than letting the parse
    # failure swallow the whole series.
    levels = _query(
        f'sum by (compose_service, level) ('
        f'count_over_time({{compose_service=~"{_SVC_RE}"}} '
        f'| json | __error__="" | level=~"error|warn" [{LOOKBACK}])'
        f')'
    )
    for series in levels:
        svc = series["metric"].get("compose_service")
        lvl = series["metric"].get("level")
        if svc not in result or lvl not in ("error", "warn"):
            continue
        result[svc][f"{lvl}_log_count"] = _value(series)

    # Total log volume — a useful signal on its own: it collapses when a service
    # dies and spikes when one starts erroring.
    totals = _query(
        f'sum by (compose_service) ('
        f'count_over_time({{compose_service=~"{_SVC_RE}"}} [{LOOKBACK}])'
        f')'
    )
    for series in totals:
        svc = series["metric"].get("compose_service")
        if svc in result:
            result[svc]["total_log_count"] = _value(series)

    for svc in result:
        result[svc]["problem_log_count"] = (
            result[svc]["error_log_count"] + result[svc]["warn_log_count"]
        )

    return result


def _value(series):
    """Pull the scalar out of an instant-query series."""
    try:
        return int(float(series["value"][1]))
    except (KeyError, ValueError, IndexError):
        return 0


if __name__ == "__main__":
    import json
    print(json.dumps(collect_logs(), indent=2))
