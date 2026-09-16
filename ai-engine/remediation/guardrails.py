"""Safety checks that sit between deciding on an action and performing it.

A false positive in detection wastes an alert. A false positive in remediation
restarts a healthy production service. The two therefore do not share a bar:
acting should require materially more confidence than alerting does.

Most of these exist to bound the damage a *wrong* detector can do. The global
rate limit is the important one -- it is a circuit breaker on the automation
itself. If the model degrades and starts flagging everything, the limit trips
and a human is called instead of the fleet being restarted one service at a
time.

Every refusal is returned with a reason rather than silently dropped, because
"the system considered acting and declined, for this reason" is exactly what you
want in the log when reviewing an incident afterwards.
"""

from datetime import timedelta


class Decision:
    """The outcome of running an action past the guardrails."""

    def __init__(self, allowed, reason, action=None, target=None,
                 service=None, symptom=None, severity=None, at=None):
        self.allowed = allowed
        self.reason = reason
        self.action = action
        self.target = target
        self.service = service
        self.symptom = symptom
        self.severity = severity
        self.at = at

    def __repr__(self):
        verdict = "ALLOW" if self.allowed else "BLOCK"
        return "<{} {} on {} ({})>".format(
            verdict, self.action, self.target, self.reason)

    def as_dict(self):
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "action": self.action,
            "target": self.target,
            "service": self.service,
            "symptom": self.symptom,
            "severity": self.severity,
            "at": self.at.isoformat() if self.at else None,
        }


class Guardrails:
    """Stateful policy checks applied in order, cheapest and hardest first."""

    def __init__(self,
                 cooldown_seconds=300,
                 max_actions_per_hour=6,
                 blast_radius=1,
                 min_severity=1.0,
                 allow_destructive=False):
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.max_actions_per_hour = max_actions_per_hour
        self.blast_radius = blast_radius
        self.min_severity = min_severity
        # Destructive actions stay off until explicitly enabled, so the default
        # posture is "recommend" rather than "restart".
        self.allow_destructive = allow_destructive

        self.last_action_at = {}   # target -> datetime
        self.recent_actions = []   # [datetime] within the trailing hour
        self.in_flight = set()     # targets currently being acted on

    def _prune(self, now):
        cutoff = now - timedelta(hours=1)
        self.recent_actions = [t for t in self.recent_actions if t >= cutoff]

    def check(self, now, action, target, meta, severity):
        """Return (allowed, reason). Order matters: hard stops come first."""
        self._prune(now)

        if action == "investigate":
            return False, "no safe automatic action for this symptom"

        if meta.get("destructive") and not self.allow_destructive:
            return False, "destructive action requires explicit approval"

        if severity is not None and severity < self.min_severity:
            return False, "severity {:.2f} below action threshold {:.2f}".format(
                severity, self.min_severity)

        if len(self.recent_actions) >= self.max_actions_per_hour:
            # Deliberately phrased as a fleet-level stop: if this many actions
            # are needed in an hour, the detector is more likely wrong than the
            # fleet is.
            return False, "global rate limit reached ({}/hour) - escalating to a human".format(
                self.max_actions_per_hour)

        if len(self.in_flight) >= self.blast_radius:
            return False, "blast radius reached ({} action in flight)".format(
                len(self.in_flight))

        last = self.last_action_at.get(target)
        if last and (now - last) < self.cooldown:
            remaining = int((self.cooldown - (now - last)).total_seconds())
            return False, "cooldown on {} for another {}s".format(target, remaining)

        return True, "permitted"

    def record(self, now, target):
        """Register an action that was actually performed."""
        self.last_action_at[target] = now
        self.recent_actions.append(now)
        self.in_flight.add(target)

    def release(self, target):
        """Mark an action finished, freeing blast-radius capacity."""
        self.in_flight.discard(target)
