# Cross-resource arbitration — implementation boundary and pending design

Status: **design incomplete; no cross-resource transaction is implemented.** The previous Phase C hierarchy described intended guarantees as present. This review corrects that claim. See [Phase C safety review](PHASE_C_SAFETY_REVIEW.md).

## Actual asynchronous graph

```text
request -> reserve: LeaseManager._lock [pending++, cancel same-resource cooldown] -> unlock
        -> emit_blocking -> policy stop action -> ProcessSupervisor._lock
             -> await process event callbacks / backend.stop / stop verification
             -> unlock supervisor
        -> activate: LeaseManager._condition -> wait/grant identical-resource lease -> unlock
        -> upstream execution / response lifetime
        -> on uncertainty, inhibit BEFORE reservation close/release
        -> cooldown worker: lease mutex check -> unlock -> idle event -> policy -> supervisor.start
```

The resource lease is a logical claim; it is not a second mutex held continuously with the manager mutex. The actual supervisor lock is `_lock`, not `_action_lock`. The supervisor has no LeaseManager dependency and no atomic pre-spawn resource guard. Resource names in the gateway are `gpu.inference` and `gpu.model_loading`, not `gpu.model`.

Current guarantees:

- Pending registration/cooldown cancellation precede blocking hooks. Activation, cancellation, abandonment, release and inhibition have offline regressions inherited from Phase B.
- Shared/exclusive conflicts apply only to the **same resource name**. Exclusive model loading does not block inference on a different name. Pending exclusive requests do not receive writer preference.
- Same-resource arrivals can cancel the tracked idle task while delayed restart is running. Supervisor start/stop calls serialize with each other; the stop action's initial status snapshot is outside that mutex but no longer skips the serialized supervisor stop.
- Idle actions now conservatively check all tracked resources, including holds with no registered policy. This fixes ignored model-load uncertainty, but the check is a snapshot: it does not serialize competing resource arrival with spawn. Other-resource cooldowns may also defer restart indefinitely.
- Unconfigured model-load HTTP routes now reject with 503 unless a matching blocking listener exists. A wildcard/no-op/custom hook satisfies this check; it does not certify a safe stop policy. Do not enable model-load hooks for the supervised inference-only experiment.

## Deadlock/cancellation risks

No built-in nested lease/supervisor mutex inversion was established in this review: the manager normally unlocks before process hooks. Holding a proposed global mutex across hook execution would introduce new risk, because callbacks can request leases. Likewise, adding an awaited manager guard while holding the supervisor mutex can invert a future manager-to-supervisor order. The old hierarchy plus pre-start pseudocode was therefore not a complete implementable solution.

The supervisor still awaits process-event callbacks while holding its mutex. A callback reentering start/stop can deadlock. Observational callbacks are awaited by the dispatcher despite their non-blocking label; a hung listener can delay cancellation or cleanup. An arbitrary callback can suppress cancellation or spawn outside supervision. These are trust/implementation limits, not established safe extension points.

The STOPPED-snapshot race in `StopProcessAction` is now fixed: it always enters serialized supervisor stop before reporting success. This handles a start already awaiting under that mutex. It does not prevent a different resource or independent action from starting the process after stop completes but before/during inference; no conflict intent spans that interval. Cancellation after an external side effect also needs ownership/result reconciliation.

## Required follow-up design

1. Define physical conflict groups mapping model operations, inference and affected processes to one arbitration domain, preserving generic triggers/actions/events.
2. Reserve all conflict intent before hooks and serialize restart intent against every conflicting arrival. Recheck intent after awaited preparation and immediately before OS side effects; reconcile after cancellation. Make pre-stop checks part of that serialization.
3. Never hold the lease-state mutex while waiting on callbacks, process operations, conflicting lease release or disk writes. Specify a real acyclic wait graph and transaction boundaries before choosing locks. Avoid an awaited manager acquisition from inside a supervisor lock.
4. Define exclusive-writer precedence, manual override semantics, multi-resource cooldown eligibility and failure behavior. Unknown/uncertain always prevents restart.
5. Add deterministic tests for model load versus active/pending inference, cross-resource arrival during delayed restart, callbacks reentering manager/supervisor APIs, simultaneous cooldowns, and cancellation at each external-action boundary.

Do not implement the old three-level hierarchy verbatim or call it verified. General mixed-resource execution remains blocked. A future supervised test may avoid it only through an explicitly enforced single inference domain/client with preloaded Qwen, model mutation disabled, and no independently triggered process actions.
