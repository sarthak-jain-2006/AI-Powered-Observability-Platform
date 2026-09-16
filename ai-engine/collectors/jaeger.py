import requests
from config import JAEGER_URL, SERVICES
from utils.logger import get_logger

log = get_logger("jaeger")

# Traces pulled per service per round. Enough to be representative at our load
# levels without making every snapshot drag in megabytes of JSON.
TRACE_LIMIT = 100


def _fetch_traces(service, lookback="1m"):
    """Fetch recent traces that involve a given service."""
    try:
        resp = requests.get(
            f"{JAEGER_URL}/api/traces",
            params={"service": service, "lookback": lookback, "limit": TRACE_LIMIT},
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json().get("data") or []
    except Exception as e:
        log.error(f"Jaeger query error for {service}: {e}")
        return []


def _span_service(span, processes):
    """Resolve which service emitted a span via its processID."""
    proc = processes.get(span.get("processID"), {})
    return proc.get("serviceName")


def _is_error(span):
    """True if the span carries an error marker."""
    for tag in span.get("tags", []):
        key, val = tag.get("key"), tag.get("value")
        if key == "error" and val is True:
            return True
        if key == "otel.status_code" and val == "ERROR":
            return True
        if key == "http.status_code":
            try:
                if int(val) >= 500:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def _percentile(values, pct):
    """Nearest-rank percentile. Avoids pulling numpy into the collector."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round(pct * len(ordered) + 0.5)) - 1, len(ordered) - 1)
    return ordered[max(idx, 0)]


def collect_traces():
    """Trace-derived features per service, plus the live dependency graph.

    Returns {
      "services": { svc: {span_count, span_error_rate, span_p95_latency,
                          downstream_call_count} },
      "edges":    { "caller->callee": call_count }
    }
    """
    # One trace spans several services, so the same trace comes back from more
    # than one per-service query. Dedupe by traceID before aggregating or every
    # multi-service request gets counted repeatedly.
    traces = {}
    for svc in SERVICES:
        for trace in _fetch_traces(svc):
            tid = trace.get("traceID")
            if tid and tid not in traces:
                traces[tid] = trace

    stats = {
        svc: {"count": 0, "errors": 0, "durations": [], "downstream": 0}
        for svc in SERVICES
    }
    edges = {}

    for trace in traces.values():
        processes = trace.get("processes", {})
        spans = trace.get("spans", [])

        # spanID -> emitting service, needed to resolve parent/child edges
        span_owner = {}
        for span in spans:
            sid = span.get("spanID")
            if sid:
                span_owner[sid] = _span_service(span, processes)

        for span in spans:
            svc = _span_service(span, processes)
            if svc not in stats:
                continue

            stats[svc]["count"] += 1
            # Jaeger reports duration in microseconds; seconds keeps this on the
            # same scale as the Prometheus latency features.
            stats[svc]["durations"].append(span.get("duration", 0) / 1_000_000)
            if _is_error(span):
                stats[svc]["errors"] += 1

            for ref in span.get("references", []):
                if ref.get("refType") != "CHILD_OF":
                    continue
                parent = span_owner.get(ref.get("spanID"))
                # Only cross-service edges: intra-service spans aren't calls.
                if parent and parent != svc:
                    edges[f"{parent}->{svc}"] = edges.get(f"{parent}->{svc}", 0) + 1
                    if parent in stats:
                        stats[parent]["downstream"] += 1

    services = {}
    for svc, s in stats.items():
        count = s["count"]
        services[svc] = {
            "span_count": count,
            "span_error_rate": round(s["errors"] / count, 4) if count else 0.0,
            "span_p95_latency": round(_percentile(s["durations"], 0.95), 4),
            "downstream_call_count": s["downstream"],
        }

    return {"services": services, "edges": edges}


if __name__ == "__main__":
    import json
    print(json.dumps(collect_traces(), indent=2))
