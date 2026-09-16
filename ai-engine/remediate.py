"""Replay collected telemetry and score what remediation would have done.

Nothing is executed. The point is to answer "would it have picked the right
action?" across every labelled fault already on disk, before anything is
permitted to touch a container. That evaluation is cheap, repeatable, and is the
only honest way to earn confidence in an automated responder.

Usage:
    python remediate.py                      # replay with the z-score detector
    python remediate.py --model iforest      # replay with the trained forest
    python remediate.py --allow-destructive  # see what the guardrails would permit
"""

import argparse
import os
import sys

from detect import (
    Detector, IForestDetector, load_snapshots, load_fault_windows,
    parse_ts, blame_root_cause, build_edges, filter_since, MIN_SCHEMA,
    DEFAULT_SNAPSHOTS, DEFAULT_EVENTS, DEFAULT_MODEL_DIR,
)
from remediation import runbook
from remediation.actions import get_executor
from remediation.engine import RemediationEngine
from remediation.guardrails import Guardrails

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ACTION_LOG = os.path.join(HERE, "data", "remediation_actions.jsonl")


def replay(rows, windows, detector, engine):
    """Walk the telemetry in order, proposing an action at every tick."""
    edges = build_edges(rows)
    decisions = []

    for row in rows:
        ts = parse_ts(row["timestamp"])
        findings = detector.check(row)
        if not findings:
            continue
        decision = engine.propose(findings, edges, ts,
                                  all_metrics=row.get("metrics"))
        if decision.action is None:
            continue
        engine.act(decision, context={"timestamp": row["timestamp"]})
        decisions.append(decision)

    return decisions


def report(decisions, windows):
    print("\n" + "=" * 78)
    print("Remediation replay - no actions were executed")
    print("=" * 78)

    if not windows:
        print("\nNo labelled fault windows. Run a fault to generate ground truth.")
        _summarise(decisions)
        return

    print("\nPer-fault decisions\n")
    correct = 0
    localised = 0
    matched = set()

    for w in windows:
        expected = runbook.EXPECTED_ACTION.get(w["fault"], "?")
        inside = []
        for i, d in enumerate(decisions):
            if d.at < w["start"]:
                continue
            if w["end"] and d.at > w["end"]:
                continue
            matched.add(i)
            inside.append(d)

        if not inside:
            print("  {:<16} no decision proposed        expected {}".format(
                w["fault"], expected))
            continue

        # Score whether the right action was reached, and how quickly -- not
        # whichever action came first. Escalating from a cheap mitigation to a
        # destructive one as evidence accumulates is good incident response, and
        # grading only the opening move would mark that behaviour wrong.
        hit = next((d for d in inside if d.action == expected), None)
        first = inside[0]
        actionable = next((d for d in inside if d.action != "investigate"), None)

        correct += 1 if hit else 0
        localised += 1 if first.service == w["service"] else 0

        if hit:
            print("  {:<16} +{:>4.0f}s  {:<20} expected {:<20} [OK]".format(
                w["fault"], (hit.at - w["start"]).total_seconds(),
                hit.action, expected))
        else:
            got = actionable.action if actionable else first.action
            print("  {:<16} {:>6}  {:<20} expected {:<20} [MISS]".format(
                w["fault"], "--", got, expected))

        print("  {:<16}        blamed {:<16} truth {:<16} {}".format(
            "", first.service, w["service"],
            "" if first.service == w["service"] else "<- localisation miss"))

        path = []
        for d in inside:
            if not path or path[-1][0] != d.action:
                path.append((d.action, (d.at - w["start"]).total_seconds()))
        if len(path) > 1:
            print("  {:<16}        escalation: {}".format(
                "", " -> ".join("{}@+{:.0f}s".format(a, t) for a, t in path)))

        blocked = [d for d in inside if d.action == expected and not d.allowed]
        if blocked:
            print("  {:<16}        would be blocked: {}".format("", blocked[0].reason))

    n = len(windows)
    print("\n  Correct action     {}/{}".format(correct, n))
    print("  Correct service    {}/{}".format(localised, n))

    stray = [d for i, d in enumerate(decisions) if i not in matched]
    print("  Decisions outside any fault window: {}".format(len(stray)))
    _summarise(decisions)


def _summarise(decisions):
    allowed = [d for d in decisions if d.allowed]
    blocked = [d for d in decisions if not d.allowed]

    print("\n" + "-" * 78)
    print("Guardrails: {} would proceed, {} blocked".format(len(allowed), len(blocked)))

    reasons = {}
    for d in blocked:
        reasons[d.reason] = reasons.get(d.reason, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("  {:>5}x  {}".format(count, reason))


def main():
    ap = argparse.ArgumentParser(description="Replay telemetry and score remediation decisions.")
    ap.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--events", default=DEFAULT_EVENTS)
    ap.add_argument("--model", choices=["zscore", "iforest"], default="zscore")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--action-log", default=DEFAULT_ACTION_LOG)
    ap.add_argument("--cooldown", type=int, default=300)
    ap.add_argument("--max-per-hour", type=int, default=6)
    ap.add_argument("--min-severity", type=float, default=1.0)
    ap.add_argument("--since", help="ISO timestamp; only report on data after this")
    ap.add_argument("--allow-destructive", action="store_true",
                    help="let the guardrails permit restarts; still never executed")
    args = ap.parse_args()

    if not os.path.exists(args.snapshots):
        sys.exit("No snapshot file at {}".format(args.snapshots))

    rows, skipped = load_snapshots(args.snapshots)
    if skipped:
        print("Skipped {} snapshots below schema v{}.".format(skipped, MIN_SCHEMA))
    if not rows:
        sys.exit("No usable snapshots.")

    detector = (IForestDetector(args.model_dir, min_severity=args.min_severity)
                if args.model == "iforest" else Detector())

    engine = RemediationEngine(
        guardrails=Guardrails(
            cooldown_seconds=args.cooldown,
            max_actions_per_hour=args.max_per_hour,
            min_severity=args.min_severity,
            allow_destructive=args.allow_destructive,
        ),
        executor=get_executor("dry-run", log_path=args.action_log),
        blame_fn=blame_root_cause,
    )

    windows = load_fault_windows(args.events)
    rows, windows = filter_since(rows, windows, args.since)
    print("Replaying {} snapshots against {} fault window(s) using the {} detector.".format(
        len(rows), len(windows), args.model))

    decisions = replay(rows, windows, detector, engine)
    if args.since:
        # Detection needed the full history; the report covers only this run.
        cutoff = parse_ts(args.since)
        decisions = [d for d in decisions if d.at >= cutoff]
    report(decisions, windows)
    print("\nIntended actions logged to {}".format(args.action_log))


if __name__ == "__main__":
    main()
