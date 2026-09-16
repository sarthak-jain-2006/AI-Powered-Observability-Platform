"""Fit one Isolation Forest per service on normal-only telemetry.

Two decisions here matter more than any hyperparameter.

First, training data is filtered to exclude every labelled fault window. A
detector fitted on data containing the faults learns that the faults are normal,
which is the quietest possible way to get a model that looks trained and detects
nothing.

Second, the alert threshold is taken from the distribution of scores on the
training data, NOT from IsolationForest.predict(). predict() derives its cutoff
from the `contamination` parameter, so on a clean baseline it will dutifully
flag roughly `contamination` of it as anomalous by construction -- a built-in
false alarm rate nobody chose. Scoring the normal data and cutting at a low
percentile makes the false alarm rate an explicit decision instead.

Usage:
    python train.py                      # fit on everything outside fault windows
    python train.py --percentile 0.5     # stricter: fewer false alarms
"""

import argparse
import json
import os
import sys
from datetime import timedelta

import numpy as np
from joblib import dump
from sklearn.ensemble import IsolationForest

from detect import load_snapshots, load_fault_windows, parse_ts, MIN_SCHEMA
from features_compact import CompactFeatureBuilder, feature_names

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SNAPSHOTS = os.path.join(HERE, "data", "snapshots.jsonl")
DEFAULT_EVENTS = os.path.join(HERE, "data", "fault_events.jsonl")
DEFAULT_MODEL_DIR = os.path.join(HERE, "models")

# A fault keeps distorting metrics for a while after it is recovered -- caches
# refill, queues drain, restarted containers warm up. Excluding a margin either
# side of each labelled window keeps that tail out of the "normal" set.
WINDOW_MARGIN = timedelta(seconds=120)

# Below this total request rate the system is idle, not healthy, and the two are
# not the same thing. An idle sample says nothing about how the services behave
# under load, and training on a mix teaches the model that zero traffic is
# normal -- after which ordinary traffic scores as anomalous. This is the exact
# failure that made the original 6,899-snapshot dataset useless: 99.7% of it was
# an idle system. Load generators do die mid-run, so this is a guard, not a
# formality.
MIN_REQUEST_RATE = 0.05

# Features whose value barely moves across the whole training set carry no
# information, and an Isolation Forest is unusually vulnerable to them: it splits
# on randomly chosen dimensions, so a constant column wastes a split every time
# it is picked. product-service, for example, calls nothing, so all seven of its
# downstream_call_count columns are flat zero -- with ~30 such columns out of 84,
# most random splits land on noise and the real signal gets diluted away.
#
# Selection uses the TRAINING data only -- a column is dropped for being constant
# under normal operation, never for how it behaves during a fault -- so this adds
# no label leakage.
MIN_FEATURE_STD = 1e-6


def in_any_fault_window(ts, windows):
    for w in windows:
        start = w["start"] - WINDOW_MARGIN
        end = (w["end"] + WINDOW_MARGIN) if w["end"] else None
        if ts >= start and (end is None or ts <= end):
            return True
    return False


def total_request_rate(row):
    return sum((m.get("request_rate") or 0)
               for m in (row.get("metrics") or {}).values())


def collect_normal_vectors(rows, windows):
    """Build feature vectors, keeping only healthy-and-loaded samples.

    Every row is pushed through the builder so history stays continuous; unwanted
    rows are dropped from the training set afterwards rather than skipped,
    because skipping them would leave a gap that corrupts the rolling and slope
    columns on the far side.
    """
    builder = CompactFeatureBuilder()
    kept = {}
    dropped_fault = 0
    dropped_idle = 0

    for row in rows:
        ts = parse_ts(row["timestamp"])
        faulty = in_any_fault_window(ts, windows)
        idle = total_request_rate(row) < MIN_REQUEST_RATE
        for service, vector in builder.push(row).items():
            if faulty:
                dropped_fault += 1
                continue
            if idle:
                dropped_idle += 1
                continue
            kept.setdefault(service, []).append(vector)

    return kept, (dropped_fault, dropped_idle), builder


def main():
    ap = argparse.ArgumentParser(description="Fit per-service Isolation Forests on normal data.")
    ap.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--events", default=DEFAULT_EVENTS)
    ap.add_argument("--out", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--estimators", type=int, default=200)
    ap.add_argument("--target-fa", type=float, default=2.0,
                    help="target false-alarm rate in percent; the threshold is set "
                         "at exactly this percentile of the training scores, so "
                         "every service is calibrated to the same rate")
    ap.add_argument("--min-samples", type=int, default=300,
                    help="refuse to train a service with less history than this")
    args = ap.parse_args()

    if not os.path.exists(args.snapshots):
        sys.exit("No snapshot file at {}".format(args.snapshots))

    rows, skipped = load_snapshots(args.snapshots)
    if skipped:
        print("Skipped {} snapshots below schema v{}.".format(skipped, MIN_SCHEMA))
    if not rows:
        sys.exit("No usable snapshots.")

    windows = load_fault_windows(args.events)
    print("Loaded {} snapshots, {} labelled fault window(s).".format(len(rows), len(windows)))

    per_service, (dropped_fault, dropped_idle), builder = collect_normal_vectors(rows, windows)
    if not per_service:
        sys.exit("No training vectors produced -- not enough history yet.")

    print("Dropped {} vectors inside fault windows (+/-{}s margin).".format(
        dropped_fault, int(WINDOW_MARGIN.total_seconds())))
    if dropped_idle:
        print("Dropped {} vectors from an idle system (load generator down).".format(
            dropped_idle))

    os.makedirs(args.out, exist_ok=True)
    names = feature_names()
    trained, refused = 0, []

    print()
    for service in sorted(per_service):
        X = np.asarray(per_service[service], dtype=float)
        if X.shape[0] < args.min_samples:
            refused.append((service, X.shape[0]))
            continue

        keep = np.where(X.std(axis=0) > MIN_FEATURE_STD)[0]
        if len(keep) < 4:
            refused.append((service, X.shape[0]))
            continue
        dropped_cols = X.shape[1] - len(keep)
        X = X[:, keep]

        # No feature scaling: Isolation Forest splits on thresholds per feature,
        # so it is invariant to monotonic rescaling. One less transform to keep
        # identical between training and inference.
        model = IsolationForest(
            n_estimators=args.estimators,
            contamination="auto",
            random_state=42,
            n_jobs=-1,
        ).fit(X)

        # Higher score_samples = more normal, so the anomalous end is the low
        # tail and the threshold is a low percentile of the training scores.
        #
        # Setting it directly from a target false-alarm rate is what makes the
        # per-service models comparable. A shape-based rule (median minus k*MAD)
        # produced wildly different false-alarm rates per service -- 6% on
        # payment-service against 18% on cart-service -- because their score
        # distributions have different shapes. Root-cause analysis then broke:
        # cart-service fired three times as often as anyone else for no reason
        # related to the fault, and being a leaf in the call graph it won the
        # blame almost every time. Calibrating each service to the same false
        # alarm rate removes that bias by construction.
        scores = model.score_samples(X)
        threshold = float(np.percentile(scores, args.target_fa))

        dump({
            "model": model,
            "threshold": threshold,
            # Inference must select the same columns in the same order, so the
            # indices travel with the model rather than being recomputed.
            "keep_indices": keep.tolist(),
            "feature_names": [names[i] for i in keep],
            "all_feature_names": names,
            "n_samples": int(X.shape[0]),
            "n_features": int(X.shape[1]),
            "target_fa": args.target_fa,
            "score_mean": float(scores.mean()),
            "score_std": float(scores.std()),
        }, os.path.join(args.out, service + ".joblib"))

        print("  {:<16} {:>5} samples x {:>3} features (dropped {:>2} constant)   threshold {:+.4f}".format(
            service, X.shape[0], X.shape[1], dropped_cols, threshold))
        trained += 1

    print("\nTrained {} model(s) -> {}".format(trained, args.out))
    for service, n in refused:
        print("  SKIPPED {:<16} only {} normal samples (need {})".format(
            service, n, args.min_samples))

    if trained:
        meta = {
            "trained_from": args.snapshots,
            "snapshots": len(rows),
            "fault_windows": len(windows),
            "target_fa": args.target_fa,
            "feature_names": names,
        }
        with open(os.path.join(args.out, "metadata.json"), "w") as f:
            json.dump(meta, f, indent=2)


if __name__ == "__main__":
    main()
