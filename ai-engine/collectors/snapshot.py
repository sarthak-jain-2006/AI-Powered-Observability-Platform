import json
import os
import time
from datetime import datetime, timezone

from config import SNAPSHOT_FILE, COLLECT_INTERVAL
from collectors.prometheus import collect_metrics
from collectors.loki import collect_logs
from collectors.jaeger import collect_traces
from utils.logger import get_logger

log = get_logger("snapshot")

# Bumped when the snapshot shape changes.
#   v1 - metrics only, no logs or traces
#   v2 - logs and traces added
#   v3 - cpu_cores added to metrics
# The feature builder expects v3, so older rows are filtered out rather than
# silently contributing rows with a missing column.
SCHEMA_VERSION = 3

# A collector that overruns this share of the interval is considered degraded.
BUDGET_SHARE = 0.4
# How many rounds to skip a degraded collector before trying it again.
BACKOFF_ROUNDS = 6


class Budgeted:
    """Wraps a collector so a slow backend costs samples, not sampling rate.

    The failure this exists to prevent: Jaeger's query cost grew as its trace
    store filled, each round took longer than the last, and the collection
    interval stretched from 10s to nearly 6 minutes. Nothing crashed, so nothing
    announced it -- the data just quietly became unevenly spaced, which corrupts
    every rate, delta and slope computed downstream.

    Sampling regularity is worth more than completeness here, so a collector
    that blows its budget is dropped for a few rounds and its block comes back
    empty. A gap in one modality is obvious in the data; a silently varying
    sample interval is not.
    """

    def __init__(self, name, fn, fallback, budget_seconds):
        self.name = name
        self.fn = fn
        self.fallback = fallback
        self.budget = budget_seconds
        self.skip_until_round = 0
        self.round = 0

    def __call__(self):
        self.round += 1

        if self.round < self.skip_until_round:
            return self.fallback() if callable(self.fallback) else self.fallback

        started = time.monotonic()
        try:
            result = self.fn()
        except Exception as e:
            log.error("%s collector failed: %s", self.name, e)
            return self.fallback() if callable(self.fallback) else self.fallback

        elapsed = time.monotonic() - started
        if elapsed > self.budget:
            self.skip_until_round = self.round + BACKOFF_ROUNDS
            log.warning(
                "%s collector took %.1fs (budget %.1fs) - skipping it for %d rounds "
                "to keep the sampling interval stable",
                self.name, elapsed, self.budget, BACKOFF_ROUNDS)
        return result


_budget = max(1.0, COLLECT_INTERVAL * BUDGET_SHARE)

_collect = {
    "metrics": Budgeted("prometheus", collect_metrics, dict, _budget),
    "logs": Budgeted("loki", collect_logs, dict, _budget),
    "traces": Budgeted("jaeger", collect_traces,
                       lambda: {"services": {}, "edges": {}}, _budget),
}


def take_snapshot():
    """Collect one full system snapshot and append it to the snapshot file."""
    # Modalities stay in separate top-level blocks rather than being merged into
    # one flat per-service vector, so a metrics-only / +logs / +traces ablation
    # is just a choice of which keys to load.
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "metrics": _collect["metrics"](),
        "logs": _collect["logs"](),
        "traces": _collect["traces"](),
    }

    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    with open(SNAPSHOT_FILE, "a") as f:
        f.write(json.dumps(snapshot) + "\n")

    log.info(f"Snapshot @ {snapshot['timestamp']} | {_summary(snapshot)}")
    return snapshot


def _summary(snapshot):
    """One-line visibility into what was just captured."""
    metrics = snapshot.get("metrics", {})
    logs = snapshot.get("logs", {})
    parts = []
    for svc, m in metrics.items():
        err = m.get("error_rate", 0)
        problems = logs.get(svc, {}).get("problem_log_count", 0)
        if err or problems:
            parts.append(f"{svc}:err={err},logs={problems}")
    if not parts:
        return f"{len(metrics)} services nominal"
    return " ".join(parts)
