"""Rolling z-score anomaly detector over the snapshot stream.

Deliberately the simplest thing that can work: a per-service, per-feature
rolling baseline plus a couple of deterministic rules. Every more sophisticated
model has to beat this to justify its existence, so it is the benchmark rather
than a throwaway.

Known limitation: the rolling baseline adapts to slow drift, so a gradual memory
leak becomes "normal" within a window or two and stops being flagged. Step
changes it catches easily. The Isolation Forest detector addresses this through
long-horizon slope features rather than through a sequence model.

Usage:
    python detect.py                      # z-score baseline, batch report
    python detect.py --model iforest      # trained Isolation Forest
    python detect.py --follow             # stream new snapshots live
    python detect.py --window 30 --threshold 3.0
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SNAPSHOTS = os.path.join(HERE, "data", "snapshots.jsonl")
DEFAULT_EVENTS = os.path.join(HERE, "data", "fault_events.jsonl")
DEFAULT_MODEL_DIR = os.path.join(HERE, "models")

# Rows below this predate the current feature set and are skipped.
MIN_SCHEMA = 3

# Features to watch, as (snapshot block, field, absolute-change floor, std floor).
# The floors matter more than the z threshold: at idle a feature sits at exactly
# zero, std collapses to zero, and without a floor any nonzero reading becomes an
# infinite z-score. The absolute floor says "ignore changes too small to care
# about" and the std floor keeps the divisor sane.
FEATURES = [
    ("metrics", "error_rate",        0.02, 0.01),
    ("metrics", "p95_latency",       0.10, 0.05),
    ("metrics", "memory_mb",        20.00, 5.00),
    ("logs",    "problem_log_count", 3.00, 1.00),
    ("traces",  "span_error_rate",   0.02, 0.01),
    ("traces",  "span_p95_latency",  0.10, 0.05),
]


def parse_ts(s):
    """Parse the timestamp formats the two producers emit.

    Snapshots come from Python isoformat (+00:00, 6 fractional digits);
    fault events come from the PowerShell "o" format (Z, 7 fractional digits).
    """
    s = s.strip().replace("Z", "+00:00")
    if "." in s:
        head, _, tail = s.partition(".")
        offset = ""
        for marker in ("+", "-"):
            if marker in tail:
                offset = tail[tail.index(marker):]
                tail = tail[:tail.index(marker)]
                break
        digits = "".join(c for c in tail if c.isdigit())[:6]
        s = head + "." + digits.ljust(6, "0") + offset
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def feature_value(snapshot, block, field, service):
    """Pull one feature for one service, tolerating missing modalities."""
    data = snapshot.get(block) or {}
    if block == "traces":
        data = data.get("services") or {}
    return (data.get(service) or {}).get(field)


def services_in(snapshot):
    return sorted((snapshot.get("metrics") or {}).keys())


def rule_findings(metrics, service):
    """Deterministic checks shared by every detector.

    These are assertions, not inferences. A model should never be asked whether
    a service that failed to scrape is down, and a rule costs no warm-up and has
    no false positives.
    """
    findings = []
    # `up` is None when Prometheus itself was unreachable, which is not the same
    # as a service being scraped and found dead.
    if metrics.get("up") == 0:
        findings.append({
            "service": service, "feature": "up", "kind": "rule",
            "detail": "service is down (up == 0)",
        })
    if (metrics.get("error_rate") or 0) > 0.5:
        findings.append({
            "service": service, "feature": "error_rate", "kind": "rule",
            "detail": "error_rate {:.2f} > 0.50".format(metrics["error_rate"]),
        })
    return findings


class Detector:
    """Per-(service, feature) rolling baseline with a deterministic rule layer."""

    def __init__(self, window=30, threshold=3.0, consecutive=2):
        self.window = window
        self.threshold = threshold
        self.consecutive = consecutive
        self.history = defaultdict(lambda: deque(maxlen=window))
        self.streak = defaultdict(int)

    def _stats(self, values):
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        return mean, var ** 0.5

    def check(self, snapshot):
        """Return the list of findings for a single snapshot."""
        findings = []

        for svc in services_in(snapshot):
            metrics = (snapshot.get("metrics") or {}).get(svc) or {}
            findings.extend(rule_findings(metrics, svc))

            # --- Statistical layer ---
            for block, field, min_delta, std_floor in FEATURES:
                value = feature_value(snapshot, block, field, svc)
                if value is None:
                    continue
                key = (svc, field)
                hist = self.history[key]

                if len(hist) >= max(5, self.window // 3):
                    mean, std = self._stats(list(hist))
                    delta = value - mean
                    z = delta / max(std, std_floor)
                    # Positive-only: every one of these features is "higher is
                    # worse", so a drop below baseline is not a fault.
                    if z > self.threshold and delta > min_delta:
                        self.streak[key] += 1
                        if self.streak[key] >= self.consecutive:
                            findings.append({
                                "service": svc, "feature": field, "kind": "zscore",
                                "detail": "{}={:.3f} vs baseline {:.3f} (z={:.1f})".format(
                                    field, value, mean, z),
                            })
                    else:
                        self.streak[key] = 0

                hist.append(value)

        return findings


class IForestDetector:
    """Per-service Isolation Forest scoring, with the same rule layer.

    Deliberately exposes the same check(snapshot) interface as Detector so the
    reporting, episode grouping and root-cause code are shared and the two
    detectors stay directly comparable.

    Features come from the same FeatureBuilder used at training time -- that is
    the point of keeping feature construction in one module. The builder needs
    its long window filled before it emits anything, so this detector stays
    silent through warm-up rather than scoring vectors the model never saw.
    """

    def __init__(self, model_dir, min_severity=0.0, consecutive=1):
        from joblib import load                # imported lazily so the default
        from features_compact import CompactFeatureBuilder

        # These gates default to off because the threshold itself is now
        # calibrated to a chosen false-alarm rate, and each 30s window already
        # averages three samples -- so single-sample jitter, the thing requiring
        # persistence used to suppress, has been removed upstream. Demanding two
        # consecutive windows on top of that only delayed detection by 30s and
        # cost real detections. They remain available for tuning.
        self.min_severity = min_severity
        self.consecutive = consecutive
        self.streak = {}

        if not os.path.isdir(model_dir):
            raise SystemExit(
                "No models at {}. Run train.py first.".format(model_dir))

        self.models = {}
        for entry in sorted(os.listdir(model_dir)):
            if entry.endswith(".joblib"):
                self.models[entry[:-len(".joblib")]] = load(
                    os.path.join(model_dir, entry))

        if not self.models:
            raise SystemExit(
                "No .joblib models in {}. Run train.py first.".format(model_dir))

        self.builder = CompactFeatureBuilder()
        self.warned = set()

    def check(self, snapshot):
        import numpy as np

        findings = []
        for svc in services_in(snapshot):
            metrics = (snapshot.get("metrics") or {}).get(svc) or {}
            findings.extend(rule_findings(metrics, svc))

        for svc, vector in self.builder.push(snapshot).items():
            bundle = self.models.get(svc)
            if bundle is None:
                if svc not in self.warned:
                    self.warned.add(svc)
                    print("  (no model for {}, skipping)".format(svc))
                continue

            # Select the same columns the model was fitted on. Scoring the full
            # 84-wide vector against a model trained on a subset would not error,
            # it would silently score garbage.
            x = np.asarray([vector], dtype=float)
            keep = bundle.get("keep_indices")
            if keep is not None:
                x = x[:, keep]
            score = float(bundle["model"].score_samples(x)[0])
            threshold = bundle["threshold"]
            # score_samples is higher-is-more-normal, so severity is how far
            # below the threshold the sample fell, in units of the training
            # score spread.
            spread = bundle.get("score_std") or 1.0
            severity = (threshold - score) / spread

            if score < threshold and severity >= self.min_severity:
                self.streak[svc] = self.streak.get(svc, 0) + 1
                if self.streak[svc] >= self.consecutive:
                    findings.append({
                        "service": svc, "feature": "iforest", "kind": "iforest",
                        "detail": "score {:.4f} < threshold {:.4f} (severity {:.1f})".format(
                            score, threshold, severity),
                    })
            else:
                self.streak[svc] = 0

        return findings


def load_snapshots(path):
    """Read snapshots, skipping rows older than the current schema."""
    rows, skipped = [], 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("schema_version", 1) < MIN_SCHEMA:
                skipped += 1
                continue
            rows.append(row)
    return rows, skipped


def load_fault_windows(path):
    """Turn the inject/recover event log into (start, end, fault, service) windows."""
    if not os.path.exists(path):
        return []
    open_faults, windows = {}, []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            name, ts = ev.get("fault"), parse_ts(ev["ts"])
            if ev.get("action") == "inject":
                open_faults[name] = (ts, ev.get("target_service"))
            elif ev.get("action") == "recover" and name in open_faults:
                start, svc = open_faults.pop(name)
                windows.append({"fault": name, "service": svc,
                                "start": start, "end": ts})
    # A fault injected but never recovered still counts, open-ended.
    for name, (start, svc) in open_faults.items():
        windows.append({"fault": name, "service": svc, "start": start, "end": None})
    windows.sort(key=lambda w: w["start"])
    return windows


def filter_since(rows, windows, since):
    """Restrict a report to one run -- WITHOUT truncating detector input.

    Only the fault windows are filtered here. The rows are deliberately left
    whole: stateful detectors need their history. The Isolation Forest path
    builds features from a 180-sample window, so cutting the input to a recent
    slice leaves it permanently in warm-up and it scores nothing at all --
    silently, because an empty result looks like "no anomalies found".

    Episodes are filtered by start time at report time instead.
    """
    if not since:
        return rows, windows
    cutoff = parse_ts(since)
    windows = [w for w in windows if w["start"] >= cutoff]
    return rows, windows


def build_episodes(rows, detector):
    """Collapse per-snapshot findings into contiguous episodes."""
    episodes, active = [], {}
    for row in rows:
        ts = parse_ts(row["timestamp"])
        found = detector.check(row)
        hit = {(f["service"], f["feature"]) for f in found}

        for f in found:
            key = (f["service"], f["feature"])
            if key not in active:
                active[key] = {"service": f["service"], "feature": f["feature"],
                               "kind": f["kind"], "start": ts, "end": ts,
                               "detail": f["detail"]}
            else:
                active[key]["end"] = ts
                active[key]["detail"] = f["detail"]

        for key in [k for k in active if k not in hit]:
            episodes.append(active.pop(key))

    episodes.extend(active.values())
    episodes.sort(key=lambda e: e["start"])
    return episodes


def build_edges(rows):
    """Accumulate the caller -> callee graph observed across all snapshots."""
    edges = defaultdict(int)
    for row in rows:
        for edge, count in ((row.get("traces") or {}).get("edges") or {}).items():
            if "->" in edge:
                caller, callee = edge.split("->", 1)
                edges[(caller, callee)] += count
    return dict(edges)


def blame_root_cause(candidates, edges, severities=None):
    """Pick the likely root cause from a set of simultaneously anomalous services.

    A slow or failing dependency drags its callers down with it, so the service
    that shows symptoms first is usually the caller, not the cause -- in the
    payment-failure run, order-service lit up ten seconds before payment-service
    did, purely because it surfaces payment 5xx as its own errors.

    So rather than trusting whichever alert fired first, walk the observed call
    graph and discard any candidate that calls another candidate. What survives
    is the furthest-downstream anomalous service: the one nothing else in the
    set depends on, and therefore the one that is not merely reacting.
    """
    candidates = set(candidates)
    if len(candidates) <= 1:
        return next(iter(candidates), None)

    downstream = {
        svc for svc in candidates
        if not any((svc, other) in edges for other in candidates if other != svc)
    }
    # A cycle leaves nothing downstream; fall back to the full candidate set.
    pool = downstream or candidates

    # Several services can be downstream of nothing -- leaves of the call graph
    # that simply happen to be anomalous at the same moment. Picking
    # alphabetically among them made a noisy model decide the blame. Preferring
    # the strongest signal means the service actually in trouble wins.
    if severities:
        return max(sorted(pool), key=lambda s: severities.get(s, 0.0))
    return sorted(pool)[0]


def report(rows, windows, detector, since=None):
    """Batch pass: group findings into episodes and score them against labels."""
    episodes = build_episodes(rows, detector)
    edges = build_edges(rows)
    if since:
        # Detection ran over everything; the report covers only this run.
        cutoff = parse_ts(since)
        episodes = [e for e in episodes if e["start"] >= cutoff]
        rows = [r for r in rows if parse_ts(r["timestamp"]) >= cutoff]

    print("\n" + "=" * 72)
    line = "Analysed {} snapshots".format(len(rows))
    if rows:
        line += "  ({:%Y-%m-%d %H:%M:%S} -> {:%H:%M:%S} UTC)".format(
            parse_ts(rows[0]["timestamp"]), parse_ts(rows[-1]["timestamp"]))
    print(line)
    print("=" * 72)

    if not episodes:
        print("\nNo anomalies detected.")
    else:
        print("\n{} anomaly episode(s):\n".format(len(episodes)))
        for e in episodes:
            secs = (e["end"] - e["start"]).total_seconds()
            print("  [{:%H:%M:%S}] {:<16} {:<18} {}  ({:.0f}s)".format(
                e["start"], e["service"], e["feature"], e["detail"], secs))

    if not windows:
        print("\nNo fault_events.jsonl labels found - detections are unscored.")
        print("Run faults/run-fault.ps1 to generate ground truth.")
        return

    print("\n" + "-" * 72)
    print("Scored against {} labelled fault window(s)\n".format(len(windows)))

    matched = set()
    detected = 0
    correct = 0
    for w in windows:
        first = None
        candidates = set()
        weights = {}
        for i, e in enumerate(episodes):
            if e["start"] < w["start"]:
                continue
            if w["end"] and e["start"] > w["end"]:
                continue
            matched.add(i)
            candidates.add(e["service"])
            # Count how much each service contributed, so blame follows the
            # strongest evidence rather than the alphabet.
            weights[e["service"]] = weights.get(e["service"], 0.0) + 1.0
            if first is None:
                first = e

        if first:
            detected += 1
            latency = (first["start"] - w["start"]).total_seconds()
            blamed = blame_root_cause(candidates, edges, severities=weights)
            if blamed == w["service"]:
                correct += 1
                verdict = "OK"
            else:
                verdict = "MISS"
            note = ""
            if blamed != first["service"]:
                note = "  (first symptom was {})".format(first["service"])
            print("  {:<16} DETECTED in {:4.0f}s   blamed {:<16} truth {:<16} [{}]{}".format(
                w["fault"], latency, blamed, w["service"], verdict, note))
        else:
            print("  {:<16} MISSED".format(w["fault"]))

    false_alarms = [e for i, e in enumerate(episodes) if i not in matched]
    print("\n  Detected      {}/{} faults".format(detected, len(windows)))
    print("  Root cause    {}/{} correct".format(correct, len(windows)))
    print("  False alarms  {} outside any fault window".format(len(false_alarms)))


def follow(path, detector, poll=2.0):
    """Stream mode: report findings as new snapshots land."""
    print("Following {} - Ctrl+C to stop\n".format(path))
    with open(path) as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(poll)
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("schema_version", 1) < MIN_SCHEMA:
                continue
            for finding in detector.check(row):
                print("[{:%H:%M:%S}] {:<16} {:<18} {}".format(
                    parse_ts(row["timestamp"]), finding["service"],
                    finding["feature"], finding["detail"]))


def main():
    ap = argparse.ArgumentParser(
        description="Rolling z-score anomaly detector over the snapshot stream.")
    ap.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--events", default=DEFAULT_EVENTS)
    ap.add_argument("--window", type=int, default=30,
                    help="rolling baseline length in samples (default 30 = 5min at 10s)")
    ap.add_argument("--threshold", type=float, default=3.0)
    ap.add_argument("--consecutive", type=int, default=1,
                    help="windows above threshold before firing (z-score uses 2; "
                         "iforest windows are already averaged so 1 is enough)")
    ap.add_argument("--follow", action="store_true")
    ap.add_argument("--model", choices=["zscore", "iforest"], default="zscore",
                    help="zscore is the simple baseline and stays the default so "
                         "the two remain directly comparable")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--since", help="ISO timestamp; only report on data after this")
    ap.add_argument("--min-severity", type=float, default=0.0,
                    help="iforest: how far past the threshold a score must fall")
    args = ap.parse_args()

    if not os.path.exists(args.snapshots):
        sys.exit("No snapshot file at {}".format(args.snapshots))

    if args.model == "iforest":
        detector = IForestDetector(args.model_dir,
                                   min_severity=args.min_severity,
                                   consecutive=args.consecutive)
    else:
        # The z-score path keeps its own persistence requirement: it sees raw
        # 10s samples, which do carry the jitter the windowing removes.
        detector = Detector(args.window, args.threshold,
                            max(args.consecutive, 2))

    if args.follow:
        follow(args.snapshots, detector)
        return

    rows, skipped = load_snapshots(args.snapshots)
    if skipped:
        print("Skipped {} snapshots below schema v{}.".format(skipped, MIN_SCHEMA))
    if not rows:
        sys.exit("No schema v{} snapshots to analyse yet.".format(MIN_SCHEMA))

    windows = load_fault_windows(args.events)
    rows, windows = filter_since(rows, windows, args.since)
    report(rows, windows, detector, since=args.since)


if __name__ == "__main__":
    main()
