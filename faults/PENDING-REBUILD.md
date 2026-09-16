# Pending: apply after the next service rebuild

`src/faultInjector.js` in all five services has been **updated in source but not
deployed**. The running containers still carry the original injector, so the
fault definitions are currently written against the old behaviour.

Rebuild with:

```
docker compose build product-service user-service cart-service payment-service order-service
docker compose up -d --force-recreate product-service user-service cart-service payment-service order-service
```

## Sequencing warning

**Rebuild before collecting a baseline, never between the baseline and the
campaign.** Restarting a service resets its process memory to a fresh ~80MB and
it climbs from there. `memory_mb` is one of the model's features, so a forest
trained on pre-restart data will score post-restart memory as anomalous. Both
phases have to run against processes started at the same time.

## What the new injector adds

**Gradual memory leak** — `{"mb": 300, "overSeconds": 600}` allocates
incrementally instead of all at once. This matters because a single allocation
is a step change that any threshold catches, whereas a real leak is slow drift
whose current reading looks unremarkable and only its trend reveals. Drift is
the case the 30-minute slope features exist to detect, and no other fault in the
set produces it.

**CPU duty cycle** — `{"seconds": 900, "intensity": 0.25}` spins for a fraction
of each 50ms slice instead of always running flat out, which is what gives
cpu-stress a subtle variant.

**Stoppable faults** — `/admin/inject/reset` now halts an in-flight CPU burn and
cancels a gradual leak still allocating. The old injector cannot, which is why
`cpu-stress` currently has to use a duration that self-terminates within the
episode.

## Definitions to restore afterwards

`resource/cpu-stress.json`:

```json
"holdSeconds": 180,
"inject": { "endpoint": "/admin/inject/cpu", "body": { "seconds": 900, "intensity": 1.0 } },
"severities": {
  "subtle":   { "seconds": 900, "intensity": 0.25 },
  "moderate": { "seconds": 900, "intensity": 0.5 },
  "severe":   { "seconds": 900, "intensity": 1.0 }
}
```

`resource/memory-leak.json`:

```json
"holdSeconds": 600,
"inject": { "endpoint": "/admin/inject/memory", "body": { "mb": 300, "overSeconds": 600 } },
"severities": {
  "subtle":   { "mb": 60,  "overSeconds": 600 },
  "moderate": { "mb": 150, "overSeconds": 600 },
  "severe":   { "mb": 300, "overSeconds": 300 }
}
```

The longer `holdSeconds` on memory-leak is deliberate: a three-minute episode
barely moves a thirty-minute slope, so the drift would never register.
