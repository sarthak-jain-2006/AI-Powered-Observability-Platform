"""Executors that carry out (or merely record) a chosen action.

The policy decides *what* should happen; an executor decides *how*, and whether
it happens at all. Keeping them apart means the runbook and the guardrails can
be exercised and evaluated in full without anything being able to touch a
running container.

DryRunExecutor is the default and is not a placeholder -- recording what the
system would have done, over a whole labelled fault campaign, is how action
precision gets measured before anything is trusted to act.
"""

import json
import os
from datetime import datetime, timezone


class Outcome:
    """The result of attempting an action."""

    def __init__(self, performed, detail, action=None, target=None, at=None):
        self.performed = performed
        self.detail = detail
        self.action = action
        self.target = target
        self.at = at or datetime.now(timezone.utc)

    def as_dict(self):
        return {
            "performed": self.performed,
            "detail": self.detail,
            "action": self.action,
            "target": self.target,
            "at": self.at.isoformat(),
        }


class DryRunExecutor:
    """Records the intended action without performing it."""

    name = "dry-run"
    can_execute = False

    def __init__(self, log_path=None):
        self.log_path = log_path
        self.performed = []

    def execute(self, action, target, meta, context=None):
        outcome = Outcome(
            performed=False,
            detail="DRY RUN: would {} on {}".format(action, target),
            action=action,
            target=target,
        )
        self.performed.append(outcome)
        if self.log_path:
            self._append(outcome, context or {})
        return outcome

    def _append(self, outcome, context):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        record = outcome.as_dict()
        record.update(context)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(record) + "\n")


class HttpExecutor:
    """Calls a control endpoint on the target service.

    Not wired up: the services have no circuit-breaker or timeout-adjustment
    endpoints yet, and adding them means rebuilding the service images. Present
    so the policy can already name http-backed actions and have them scored in
    dry run.
    """

    name = "http"
    can_execute = False

    def execute(self, action, target, meta, context=None):
        return Outcome(
            performed=False,
            detail="http backend unavailable: {} needs a control endpoint on {} "
                   "that does not exist yet".format(action, target),
            action=action,
            target=target,
        )


class DockerExecutor:
    """Restarts containers via the Docker socket.

    Not wired up: this needs /var/run/docker.sock mounted into the ai-engine
    container, which is root-equivalent on the host and has to be enabled
    deliberately rather than by default.
    """

    name = "docker"
    can_execute = False

    def execute(self, action, target, meta, context=None):
        return Outcome(
            performed=False,
            detail="docker backend unavailable: {} on {} requires the Docker "
                   "socket to be mounted".format(action, target),
            action=action,
            target=target,
        )


def get_executor(mode, log_path=None):
    """Only dry-run is selectable today; the others exist to be named, not run."""
    if mode == "dry-run":
        return DryRunExecutor(log_path=log_path)
    raise SystemExit(
        "Executor mode {!r} is not enabled. Only 'dry-run' is available until a "
        "real backend is turned on.".format(mode))
