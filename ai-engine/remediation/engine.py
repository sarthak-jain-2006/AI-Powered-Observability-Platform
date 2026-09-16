"""Ties detection, root cause, policy, guardrails and execution together.

The loop is:

    findings -> root cause -> symptom -> action -> guardrails -> execute
             -> verify recovery -> log outcome (or escalate)

Verification is the part that is easy to skip and shouldn't be. Without it the
system can only report that it *did* something, which is not the same as the
problem being fixed -- and if recovery did not happen, the correct response is
to escalate rather than to try the same action again. A blind retry loop against
a service that will not come back is how a small incident becomes a large one.
"""

from datetime import timedelta

from remediation import runbook
from remediation.guardrails import Decision


class RemediationEngine:
    def __init__(self, guardrails, executor, blame_fn, verify_window_seconds=180):
        self.guardrails = guardrails
        self.executor = executor
        # Injected so the engine uses exactly the same root-cause logic the
        # detector reports with, rather than a second copy that can drift.
        self.blame = blame_fn
        self.verify_window = timedelta(seconds=verify_window_seconds)
        self.history = []

    def propose(self, findings, edges, now, all_metrics=None):
        """Decide what, if anything, should be done about the current findings."""
        if not findings:
            return Decision(False, "no findings", at=now)

        # Localise first. Acting on whichever service alerted first would mean
        # restarting the caller of a sick dependency rather than the dependency.
        candidates = {f["service"] for f in findings}
        service = self.blame(candidates, edges)
        if service is None:
            return Decision(False, "no service could be blamed", at=now)

        on_service = [f for f in findings if f["service"] == service]
        symptom = runbook.dominant_symptom(on_service)

        # The measurement behind the symptom can sharpen it -- most importantly,
        # near-total failure in a live process means its dependency died, which
        # calls for a different action than partial degradation does.
        metrics = (all_metrics or {}).get(service) or {}
        symptom = runbook.refine_symptom(symptom, metrics)

        # A service reported down is not merely erroring, and that changes which
        # action is right, so the distinction is carried through explicitly.
        alive = not any(f["feature"] == "up" for f in on_service)
        action, target = runbook.choose_action(symptom, service, service_alive=alive)
        meta = runbook.ACTIONS.get(action, {})

        severity = _severity(on_service)
        allowed, reason = self.guardrails.check(now, action, target, meta, severity)

        return Decision(allowed, reason, action=action, target=target,
                        service=service, symptom=symptom, severity=severity,
                        at=now)

    def act(self, decision, context=None):
        """Execute an allowed decision; refusals are recorded, not discarded."""
        if not decision.allowed:
            self.history.append({"decision": decision.as_dict(), "outcome": None})
            return None

        meta = runbook.ACTIONS.get(decision.action, {})
        ctx = dict(context or {})
        ctx.update({
            "service": decision.service,
            "symptom": decision.symptom,
            "severity": decision.severity,
        })
        outcome = self.executor.execute(decision.action, decision.target, meta, ctx)

        # Only a real execution consumes cooldown and rate-limit budget; a dry
        # run must not, or one replay would exhaust the hourly allowance and
        # every later decision would be blocked for the wrong reason.
        if outcome.performed:
            self.guardrails.record(decision.at, decision.target)

        self.history.append({
            "decision": decision.as_dict(),
            "outcome": outcome.as_dict(),
        })
        return outcome

    def verify(self, service, rows_after, metric="error_rate", baseline=None):
        """Did the service actually return to normal after the action?

        Returns (recovered, detail). A False here means escalate to a human, not
        retry.
        """
        if not rows_after:
            return False, "no telemetry after the action"

        values = []
        for row in rows_after:
            m = (row.get("metrics") or {}).get(service) or {}
            v = m.get(metric)
            if v is not None:
                values.append(v)

        if not values:
            return False, "no {} readings for {}".format(metric, service)

        recent = values[-min(len(values), 6):]
        avg = sum(recent) / len(recent)
        target = baseline if baseline is not None else 0.05

        if avg <= target:
            return True, "{} settled to {:.3f} (target {:.3f})".format(metric, avg, target)
        return False, "{} still {:.3f}, above target {:.3f} - escalate".format(
            metric, avg, target)


def _severity(findings):
    """A crude 0..n urgency score used only as a gate, not a ranking.

    Rule findings are assertions and score highest by definition; a model score
    is trusted less than a measurement.
    """
    score = 0.0
    for f in findings:
        if f.get("kind") == "rule":
            score += 3.0
        elif f.get("kind") == "iforest":
            score += 1.5
        else:
            score += 1.0
    return score
