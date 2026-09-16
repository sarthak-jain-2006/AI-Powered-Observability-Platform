"""Compact per-service features over fixed time windows.

Replaces the 84-column builder, which was a mistake for this algorithm. An
Isolation Forest isolates points by splitting on RANDOMLY CHOSEN dimensions, so
its effectiveness degrades as the fraction of uninformative columns rises: with
49 features of which roughly eight carried signal, most splits in most trees
landed on noise and genuine one-feature faults (a latency spike on an otherwise
healthy service) never looked isolated. Fewer, better-chosen columns is not a
simplification here, it is the correctness fix.

Twelve columns per service: eight describing the current window and four
describing how it changed from the previous one. Absolute values say what the
service is doing; change values say whether it is degrading, which is what makes
gradual faults visible at all.

Rows are 30-second windows rather than raw 10s samples. Averaging three samples
removes single-scrape jitter, which otherwise shows up as anomalous all by
itself.
"""

WINDOW_SECONDS = 30
EPS = 1e-6

# (output name, snapshot block, field)
BASE = [
    ("latency_p95",             "metrics", "p95_latency"),
    ("error_rate",              "metrics", "error_rate"),
    ("throughput",              "metrics", "request_rate"),
    ("cpu_usage",               "metrics", "cpu_cores"),
    ("memory_usage",            "metrics", "memory_mb"),
    ("log_error_count",         "logs",    "error_log_count"),
    ("dependency_failure_rate", "traces",  "span_error_rate"),
    ("dependency_latency",      "traces",  "span_p95_latency"),
]

# Which of those also get a relative-change column. Chosen because these are the
# four that move when a service degrades; memory and log counts are covered by
# their absolute values.
CHANGE_OF = ["latency_p95", "error_rate", "cpu_usage", "throughput"]

FEATURE_NAMES = [n for n, _, _ in BASE] + [n + "_change" for n in CHANGE_OF]

def feature_names():
    return list(FEATURE_NAMES)


def _get(snapshot, block, field, service):
    data = snapshot.get(block) or {}
    if block == "traces":
        data = data.get("services") or {}
    value = (data.get(service) or {}).get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        # Missing telemetry is treated as zero rather than dropped: a gap in one
        # modality should not discard an otherwise usable window.
        return 0.0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def epoch(ts):
    from datetime import datetime, timezone
    if isinstance(ts, (int, float)):
        return float(ts)
    dt = datetime.fromisoformat(str(ts))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class CompactFeatureBuilder:
    """Aggregates snapshots into 30s windows and emits one vector per service.

    Warm-up is two windows (~60s), not the 180 samples the wide builder needed,
    because nothing here looks back further than the previous window. That alone
    makes the detector usable minutes after startup instead of half an hour.
    """

    def __init__(self, window_seconds=WINDOW_SECONDS):
        self.window_seconds = window_seconds
        self.buffer = {}     # service -> [(ts, {name: value})]
        self.previous = {}   # service -> previous window means
        self.windows_seen = {}

    def ready(self, service):
        return service in self.previous

    def warmup_remaining(self, service):
        return 0 if self.ready(service) else 1

    def push(self, snapshot):
        """Feed one snapshot; emit vectors only when a window closes."""
        now = epoch(snapshot.get("timestamp"))
        out = {}

        for service in sorted((snapshot.get("metrics") or {}).keys()):
            sample = {name: _get(snapshot, block, field, service)
                      for name, block, field in BASE}
            buf = self.buffer.setdefault(service, [])
            buf.append((now, sample))

            if buf[-1][0] - buf[0][0] < self.window_seconds:
                continue

            means = {name: _mean([s[name] for _, s in buf]) for name, _, _ in BASE}
            self.buffer[service] = []

            prev = self.previous.get(service)
            self.previous[service] = means
            self.windows_seen[service] = self.windows_seen.get(service, 0) + 1
            if prev is None:
                continue   # first window has nothing to compare against

            vector = [means[name] for name, _, _ in BASE]
            for name in CHANGE_OF:
                # Relative change, so a doubling reads the same whether latency
                # went 100->200ms or 1->2s. Guarded for the near-zero baselines
                # that error_rate sits at almost all the time.
                base = abs(prev[name])
                vector.append((means[name] - prev[name]) / (base + EPS)
                              if base > EPS else 0.0)
            out[service] = vector

        return out


def build_matrix(rows, min_schema=3):
    builder = CompactFeatureBuilder()
    stamps, vectors = {}, {}
    for row in rows:
        if row.get("schema_version", 1) < min_schema:
            continue
        for service, vec in builder.push(row).items():
            stamps.setdefault(service, []).append(row.get("timestamp"))
            vectors.setdefault(service, []).append(vec)
    return {s: (stamps[s], vectors[s]) for s in vectors}
