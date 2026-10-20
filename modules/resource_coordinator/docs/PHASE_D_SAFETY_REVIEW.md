# Phase D safety and integration review — 2026-10-19

Reviewed `e9b8c9f5` against `3744c4c2` on `resource-coordinator-phase-d`.
Corrections are in the commit containing this report; its hash is supplied in the final handoff.
No live process, model, inference, shared configuration, merge or push operation was performed.

## Decision

**CONDITIONAL GO for one supervised normal-path experiment only after every acceptance gate is independently verified and the user separately authorizes execution. Until then, operational NO-GO remains in force.**

This is a review outcome, not permission to execute. Unattended operation remains NO-GO.
Use [the acceptance gates](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md) and [abort procedure](EMERGENCY_ABORT_PROCEDURE.md).

## Prioritized defects and corrections

| Severity | Submitted defect / affected path | Verified correction |
| --- | --- | --- |
| Critical | `CoordinatorService.start`: READY published before awaited miner launch; abort waited on startup lock; cancellation could retain READY. | Keep PREFLIGHT through launch and positive owned-RUNNING verification. Cancel/failure synchronously freeze admission/restarts. Abort needs no process lock/status probe. |
| Critical | `stop`, lease cooldown and policy idle callback: cooldown could launch mining after STOPPED; pending-only timeout and failed pause were lost. | Synchronous terminal restart latch and supervisor manual override before any await; cancel cooldowns, gate idle callbacks, drain all active/pending resources, check pause and final absence. Uncertain/cancelled shutdown enters reconciliation. Clearing a hold cannot clear the terminal latch. |
| Critical | Gateway used admission captured before body upload/hooks/reservation activation. Abort could be followed by new stop actions or upstream forwarding. | Recheck after body, before blocking actions, after activation, and after positive process absence check immediately before send. Pending claims precede hooks. Already-forwarded requests retain uncertain-outcome protections. |
| High | `--start-miner`: resume's stopped-by-coordinator default skipped a fresh launch yet service reported ready. | Explicit initial owned launch permits fresh start and verifies the resulting identity/state. Default flags do not launch or stop external processes. |
| High | Gateway lifespan ignored an already bound service when argument omitted; absent service admitted inference; no guaranteed exit cleanup. | Resolve bound service; require managed service by default, fail startup closed, and shield cleanup in finally. Explicit `standalone=True` retains the generic unmanaged proxy API for deliberate callers; it is forbidden for this experiment. |
| High | Abort HTTP/CLI had no authentication; terminal recovery could remove restart protection. | Require bearer operator token (recovery-token fallback), nonempty bounded operator/reason, and attributed abort. Disabled without token; wrong token rejected. Terminal/unready service recovery rejected. Abort is an in-memory safety latch, not an upstream cancellation primitive. |
| High | Unknown GETs and broad suffix/prefix matching forwarded unrecognized routes. A noop load hook could authorize a separate resource domain. | Unknown reads/mutations fail closed; reviewed inference paths and single-segment metadata paths only. All managed model mutations denied pending cross-resource transactions, even with a hook. Unknown internal paths/methods cannot proxy upstream. |
| Medium | Preflight and docs overstated watchdog/upstream verification, strict shutdown bounds, persistence and test coverage. | Config/policy/executable checks plus startup process ownership checks; explicit independent environment gates and corrected procedures. Drain timeout is not a strict overall OS deadline. |

## Assembled control flow and safety contract

The real CLI calls `build_system`, creates one service and binds it to the gateway before `uvicorn.run`.
ASGI lifespan starts that same service. Without lifespan startup it remains unready; startup failure fails the application rather than serving protected requests.
The default path admits only READY traffic. Initial owned miner launch, if explicitly requested, completes before READY.

Inference body upload is followed by fresh admission, atomic reservation/cooldown cancellation, a fresh gate before blocking stop hooks, activation, fresh admission and actual supervisor STOPPED checks. The final readiness check has no suspension before scheduling upstream send.
A control signal's successful return does not substitute for positive stop verification.
Completion must establish the supported protocol's normal terminal result; errors, truncation, cancellation and uncertain outcomes inhibit restart before claims unwind. Later successful inference cannot clear an earlier hold.
The last claim starts cooldown only when restart eligibility remains valid; terminal lifecycle freezes deny restart independently of individual hold removal.
Shutdown closes admission and freezes before draining; timeout/cancellation never grants restart authority.

The built-in graph does not introduce a lease-lock to supervisor-lock cycle: reservation updates unlock before hooks; idle emission happens outside the lease mutex. Lifecycle freeze acquires neither async mutex. Existing supervisor callbacks still execute inside its mutex and may deadlock if reentrant; no custom or reentrant callbacks are allowed in the first experiment. Synchronous OS inspections or uncooperative callbacks can delay shutdown/abort responsiveness. Protections remain closed, but this requires an independent human crash-abort plan.

These guarantees are cooperative within one service/event loop and the reviewed built-in actions. They are not machine-wide GPU exclusion. A watchdog, another coordinator/process launcher, or direct LM Studio client can invalidate the physical assumptions. Direct traffic to port **1234 bypasses the coordinator entirely**.

## Routes and protocol limits

| Method / route | Managed behavior |
| --- | --- |
| POST `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/responses`, `/v1/messages` | Protected inference domain; known route does not imply every response protocol proves completion. |
| POST `/api/v0/chat/completions`, `/api/v0/completions`, `/api/v0/embeddings`, `/api/v1/chat` | Protected inference domain. Installed LM Studio version and native completion format are unverified. |
| GET/HEAD/OPTIONS model list paths; single-segment details under `/v1/models/` or `/api/v0/models/`; root | Metadata only, still readiness gated. |
| Known native model load/unload | 503 for managed service, including noop/custom hooks. |
| Unknown reads, downloads, decisions, alternative mutating methods/routes | Fail closed (501 or framework 405); no upstream forwarding. |
| `/_coordinator/status` GET | Read-only, available while unready. |
| `/_coordinator/abort` POST | Authenticated attributed latch; other methods/unknown internal paths cannot proxy. |
| `/_coordinator/recover` POST | Authenticated explicit override; all-resource-idle gate retained; terminal/unready service rejects. Never part of the first experiment. |

Preserve existing header/status/body/query and streaming proxy behavior on admitted paths. No redirects are followed. Abort cannot recall a request already sent to upstream; it closes future forwarding and restart eligibility. `/v1/messages` is conservatively uncertain without a recognized completion proof; its regression requires a hold. First test scope is only one non-streaming `/v1/chat/completions` request with normal `finish_reason=stop`, no tools.

Current [LM Studio native docs](https://lmstudio.ai/docs/developer/rest) describe `/api/v1` since 0.4.0; the historical design's 0.3.x target does not establish installed compatibility. [OpenAI compatibility docs](https://lmstudio.ai/docs/developer/openai-compat) list Responses, chat, completions and embeddings. Unknown new operations remain denied until reviewed.

## Process identity, Windows control and external supervision

Phase C exact psutil creation-time equality, executable checks and fail-closed ambiguity remain intact; no one-second tolerance was reintroduced. An external launch is not an owned process group and is not eligible for this experiment. External stop/restart/adoption and force remain false in the template.
Windows CTRL_BREAK requires the known group and shared console; new-console mode does not establish that arrangement. Backend stop waits for original identity/known children and a quiet window. Successful signal delivery is insufficient; `terminate()` would be forceful, not graceful.
A later watchdog relaunch or detached descendant remains possible outside that model. Absence of a Windows service is insufficient evidence of no application watchdog. The operator must exclude launchers, scheduled tasks, wrappers, application watchdogs and independent clients, and record exact binary/arguments/parent/group context. Signal/flush timing remains live-unverified; failure must veto inference, not enable force fallback.

See [Microsoft console control semantics](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent) and [process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags). Durable/native FILETIME and stable-handle identity remain future work.

## Validation quality and evidence

Reproduced submitted baseline: **186 tests passed**. The sixteen original scenarios mostly hand-assemble objects and omit the miner adapter; HTTPX ASGITransport alone does not run lifespan ([HTTPX documentation](https://www.python-httpx.org/advanced/transports/)). Scenario 15 used the same in-memory manager, not a process crash or durable restoration. Its expectation is now fail-closed, and its comment states that limit.

Added **34 review cases** in `tests/phase_d_safety_review_test.py`: actual factory, service-bound lifespan, CLI-to-factory/lifespan (fake uvicorn), nine inference routes, stop/reservation assertions at mock upstream send, startup interruption/failure, abort during upload/hooks/reservation observation, shutdown cooldown/pending/cancellation/failure, terminal recovery, authenticated abort, unbound startup, model mutation and unknown route shapes. Restart checks await an event instead of relying on a 40ms Windows scheduling delay. A full run also exposed the existing Phase C fake-watchdog test racing its 30ms sleep (219 passed/1 failed); it now awaits the simulated relaunch task before asserting detection.

Original Phase B/C unmanaged gateway unit tests explicitly opt into standalone mode and retain their assertions. Managed service regressions use the actual default assembly. A classifier test that previously accepted arbitrary custom prefixes now reflects the fail-closed contract; unsupported `/v1/models/load` correctly returns 501 rather than the known-native-route 503.

Final commands (from worktree root, repository venv Python):

```text
python -m pytest modules/resource_coordinator/tests -o addopts= -q --basetemp=modules/resource_coordinator/.pytest_tmp_root --tb=short
python -m ruff check modules/resource_coordinator
python -m ruff format --check --line-length 120 modules/resource_coordinator
python -m mypy --ignore-missing-imports modules/resource_coordinator/resource_coordinator
git diff --check
```

Final result: **220 passed in 4.22s**, Ruff check clean, Ruff format clean (36 files, 120 columns), Mypy clean across 16 source files, Git whitespace check clean. An initial sandboxed static-check attempt could not write caches; rerunning with authorized worktree access succeeded. This is not real TCP, real Windows process control, clean-environment package installation, live inference, physical containment or crash recovery validation.

## Supervised-test prerequisites and acceptable limitations

All acceptance gates must have independently reviewable evidence before separate user execution authorization. One GPU, one owned miner, one preloaded idle Qwen, one client, no tools/model operations, no custom callbacks, no competing control path. Confirm actual VRAM headroom empirically; model residency alone proves neither headroom nor execution idle.
Abort closes admission and cancels cooldown/restarts while process remains alive. It does not stop an already running miner or upstream generation. Operator reconciliation must handle their exact identities independently. A hung/crashed coordinator aborts the whole experiment; never restart it or clear a hold to continue. All launchers stay disabled until positive independent reconciliation.
This narrow crash-abort protocol can defer automatic recovery; it cannot make a restarted process recover safety state.

## Unattended-operation blockers

- No runtime write-ahead safety journal or crash-safe startup reconciliation. Persistence helpers are not integrated; missing/corrupt state must fail closed. Persist request intent/possibly-forwarded state, pending/active leases, inhibition causes, process/boot/config/instance identities and external actions before effects; persist terminal evidence before restart eligibility. Record attributable durable overrides. Telemetry is not this journal.
- No cross-resource transactional arbitration/conflict groups or single-instance machine-wide authority; no external launcher containment. Independent GPU/process operations require a reviewed transaction and lock/cancellation design.
- No proven stable Windows native identity/handles across recovery, watchdog/descendant containment, crash/power-loss injection or real TCP cancellation/shutdown guarantees.
- Shutdown and callbacks lack a strict total deadline; synchronous OS calls may block the loop. Add bounded callback contracts/isolation without authorizing release on timeout.
- Secure state ACLs, durable audit, startup reconciliation and recovery procedures need implementation and review.

These are not deferred polish. Packaging minimum-version tests, broader protocol support, richer metrics and callback ergonomics can wait beyond the first narrow experiment.

## Telemetry T1 reconciliation

`dd8dd7ff` remains separate; no merge/cherry-pick was performed. Preserve both branch tips. Any later authorized integration must retain this service binding/lifespan and cleanup owner, terminal latch, admission rechecks, exact identity, authentication and Phase B uncertain-A/successful-B protections. Resolve CLI/config/gateway edits individually, map actual lmstudio/resource payloads to telemetry, and run combined gateway-to-storage, failure/saturation and all safety regressions. T1's droppable observations and SQLite settings must not authorize restart or replace write-ahead safety state. See the Phase C review for the earlier mapping analysis.
