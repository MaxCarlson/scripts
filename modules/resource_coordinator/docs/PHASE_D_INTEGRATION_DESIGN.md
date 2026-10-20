# Phase D reviewed integration design

Version 2, 2026-10-19. The submitted design has been superseded by the actual-code [Phase D safety review](PHASE_D_SAFETY_REVIEW.md). Target versions and host behavior remain unverified.

## Managed service

`CLI serve -> build_system -> CoordinatorService -> gateway.create_app(service) -> ASGI lifespan`.
Startup remains INITIALIZING/PREFLIGHT until config checks, process identity checks and any explicitly requested owned launch succeed. Only READY admits protected traffic. An unbound gateway is closed by default; standalone mode is an explicit unmanaged API and is outside supervised acceptance scope.

`request -> admission -> body -> admission -> atomic pending reservation/cooldown cancellation -> admission -> blocking stop policy -> activate -> admission -> verified process absence -> admission -> upstream send -> protocol completion or uncertainty -> inhibition if uncertain -> release -> eligible cooldown`.

All managed model mutations are disabled until physical resource transactions exist. Unknown routes fail closed. Direct upstream port 1234 clients bypass the entire flow.

## Lifecycle and lock rules

CREATED -> INITIALIZING -> PREFLIGHT -> READY; failure/cancellation closes the gate.
Shutdown transitions to DRAINING and synchronously freezes supervisor starts and all manager restarts before awaiting anything. Active and pending work drain for the configured budget. Uncertain shutdown transitions to RECONCILIATION_REQUIRED; clean shutdown to STOPPED. Both retain the terminal restart latch.
Abort synchronously freezes and enters RECONCILIATION_REQUIRED without querying/signaling processes. Recovery cannot reopen a terminal service. None of these latches survives a coordinator crash.

Do not hold the lease mutex across hooks. Built-in reserve and idle events release it before supervisor work; lifecycle freeze takes no async lock. Reentrant supervisor callbacks are unsupported for the first experiment. Total shutdown is not strictly bounded: synchronous Windows inspection and callbacks can block, although restart denial stays latched.

## Scope boundaries

One owned miner, one GPU, one preloaded idle model, one sequential client, no external supervisor or independent process actions. Exact PID/creation-time/executable checks and positive stop verification remain required. Signal success is not proof of termination. No automatic crash recovery or cross-resource transaction is implemented. Follow the [acceptance gates](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md), not architectural intentions, when deciding readiness.
