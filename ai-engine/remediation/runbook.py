"""Symptom classification and the action policy.

The policy is a lookup table on purpose. An operator has to be able to read it,
predict what the system will do, and audit what it did afterwards -- and every
action taken has to be explainable in one sentence. A learned policy buys very
little here and costs all of that, so the table stays a table.

The actions are ordinary runbook entries rather than "undo the fault we
injected". The detector never learns which fault was injected; it observes a
symptom and responds the way an on-call engineer would. That distinction is what
makes the results mean anything outside this testbed.
"""

# --- Symptom classes -------------------------------------------------------
# Ordered most-specific first. A finding is classified by the first rule that
# matches, so a downed service is never reported merely as "elevated errors".

SERVICE_DOWN = "service_down"
DEPENDENCY_FAILURE = "dependency_failure"
MEMORY_PRESSURE = "memory_pressure"
CPU_SATURATION = "cpu_saturation"
HIGH_ERROR_RATE = "high_error_rate"
HIGH_LATENCY = "high_latency"
ERROR_LOG_BURST = "error_log_burst"
UNCLASSIFIED = "unclassified"

# A live service failing almost every request is a different problem from one
# failing some of them. Near-total failure in a process that is still up and
# still being scraped points at whatever it depends on rather than at the
# process itself -- a dead datastore takes every request down with it, while a
# degraded service keeps serving a share of them. This is the threshold that
# separates "restart the database" from "shed load off a wobbly service".
TOTAL_FAILURE_RATIO = 0.6

# feature name -> symptom class
_FEATURE_SYMPTOM = {
    "up": SERVICE_DOWN,
    "memory_mb": MEMORY_PRESSURE,
    "cpu_cores": CPU_SATURATION,
    "error_rate": HIGH_ERROR_RATE,
    "span_error_rate": HIGH_ERROR_RATE,
    "p95_latency": HIGH_LATENCY,
    "span_p95_latency": HIGH_LATENCY,
    "problem_log_count": ERROR_LOG_BURST,
    "error_log_count": ERROR_LOG_BURST,
    "warn_log_count": ERROR_LOG_BURST,
}

# Lower number wins when a service shows several symptoms at once.
_SYMPTOM_PRIORITY = {
    SERVICE_DOWN: 0,
    DEPENDENCY_FAILURE: 1,
    MEMORY_PRESSURE: 2,
    CPU_SATURATION: 3,
    HIGH_ERROR_RATE: 4,
    HIGH_LATENCY: 5,
    ERROR_LOG_BURST: 6,
    UNCLASSIFIED: 9,
}


def refine_symptom(symptom, metrics):
    """Sharpen a symptom using the measurement behind it.

    Only one refinement so far: near-total error rate on a process that is still
    up is reclassified from "this service is erroring" to "the thing it depends
    on has failed", because those call for different actions.
    """
    if symptom != HIGH_ERROR_RATE or not metrics:
        return symptom
    if metrics.get("up") == 0:
        return symptom
    if (metrics.get("error_rate") or 0) >= TOTAL_FAILURE_RATIO:
        return DEPENDENCY_FAILURE
    return symptom


def classify(finding):
    """Map one detector finding to a symptom class."""
    return _FEATURE_SYMPTOM.get(finding.get("feature"), UNCLASSIFIED)


def dominant_symptom(findings):
    """The symptom worth acting on when a service shows several at once."""
    if not findings:
        return UNCLASSIFIED
    return min((classify(f) for f in findings),
               key=lambda s: _SYMPTOM_PRIORITY.get(s, 99))


# --- Actions ---------------------------------------------------------------
# `destructive` gates whether an action may ever run unattended. `backend` says
# which executor performs it, so the policy stays independent of whether the
# Docker socket happens to be available.

ACTIONS = {
    "restart_service": {
        "backend": "docker",
        "destructive": True,
        "description": "Restart the service container",
    },
    "restart_dependency": {
        "backend": "docker",
        "destructive": True,
        "description": "Restart the backing datastore the service depends on",
    },
    "open_circuit_breaker": {
        "backend": "http",
        "destructive": False,
        "description": "Trip the caller's circuit breaker to shed load from the failing dependency",
    },
    "increase_timeout": {
        "backend": "http",
        "destructive": False,
        "description": "Raise the caller's timeout so slow-but-working calls stop failing",
    },
    "investigate": {
        "backend": "none",
        "destructive": False,
        "description": "Surface for a human; no safe automatic action",
    },
}

# --- Policy ----------------------------------------------------------------

RUNBOOK = {
    SERVICE_DOWN: "restart_service",
    # The service is fine; whatever it reads from is not.
    DEPENDENCY_FAILURE: "restart_dependency",
    # Restarting on memory pressure is the standard real-world leak mitigation:
    # it does not fix the bug, it buys time until someone does.
    MEMORY_PRESSURE: "restart_service",
    CPU_SATURATION: "restart_service",
    # Partial failures are better handled by shedding load from the wobbly
    # service than by restarting something that is still mostly working.
    HIGH_ERROR_RATE: "open_circuit_breaker",
    HIGH_LATENCY: "increase_timeout",
    # A log burst on its own is too weak a signal to act on automatically.
    ERROR_LOG_BURST: "investigate",
    UNCLASSIFIED: "investigate",
}

# Services whose failure is really their datastore failing. Used to turn
# "product-service is erroring" into "restart product-db" when the service
# process itself is alive.
BACKING_STORE = {
    "product-service": "product-db",
    "user-service": "user-db",
    "payment-service": "payment-db",
    "order-service": "order-db",
    "cart-service": "cart-redis",
}


def choose_action(symptom, service, service_alive=True):
    """Pick an action for a symptom, and name the thing it acts on.

    Returns (action_name, target). Most actions target the service itself;
    restart_dependency targets its backing datastore instead, since that is the
    thing that actually needs restarting.
    """
    action = RUNBOOK.get(symptom, "investigate")

    if action == "restart_dependency":
        store = BACKING_STORE.get(service)
        if not store:
            # Nothing known to restart, so do not guess at a target.
            return "investigate", service
        return action, store

    return action, service


# --- Evaluation ground truth ----------------------------------------------
# What a competent operator would do for each injected fault. Kept here rather
# than in the fault definitions so the definitions keep describing the fault and
# nothing else, and so this stays visibly a scoring key rather than an input the
# system could cheat from.

EXPECTED_ACTION = {
    "service-crash": "restart_service",
    "memory-leak": "restart_service",
    "cpu-stress": "restart_service",
    "db-down": "restart_dependency",
    "redis-down": "restart_dependency",
    "payment-failure": "open_circuit_breaker",
    "payment-delay": "increase_timeout",
    "db-delay": "increase_timeout",
}
