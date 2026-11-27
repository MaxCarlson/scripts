# Phase C safety review checkpoint — 2026-10-19

**Recommendation: NO-GO for a supervised live test in the current state.** The bounded corrections below are ready for a local commit; they do not supply a supported coordinator-owned startup path, real Windows acceptance evidence or a complete arbitration/recovery transaction. A future GO is a review outcome, never permission to execute.

Reviewed `9101ca7c` on `resource-coordinator-phase-c-prep`, against `e903cf2e`. Worktree: `C:/Users/mcarls/src/scripts/.worktrees/resource-coordinator-phase-c-prep`. Telemetry branch independently remains at `dd8dd7ff`. No merge, push, miner control, model operation, live inference, live GPU/topology probe, or shared-service/client configuration modification was performed in this review.

## P1: defects requiring correction before supervised testing

| Finding in the submitted preparation | Action and remaining boundary |
| --- | --- |
| Template selects NEW_CONSOLE while claiming a shared-console process group and disabling force, so current stop refuses | Fixed template to `new_console: false`, retaining force disabled. Mocked OS-boundary test verifies group creation and that successful signal delivery still fails stop when absence is unverified. Actual Krig behavior remains untested. |
| Template enables external stop/restart despite requiring no unmanaged miner; adopt_external=false does not negate explicit permissions | External stop/restart/adoption are now all false. Paths and wallet/worker arguments are explicit replacement placeholders. Shell-style environment substitution is not implemented and no longer implied. Any future external adoption needs a separately pinned, reviewed instance and supervisor contract. |
| Creation times differing by up to one second are accepted as the same persisted process; runtime lookup also allowed 0.05 seconds | Fixed both to exact known creation times. Nonzero tolerances are rejected. Missing/invalid identities are UNVERIFIABLE; access denial is not absence. Matching time remains only a candidate identity, requiring executable/lifecycle/boot context and protection against check-to-action races. |
| Missing/corrupt state becomes a clean empty state; loose schema can coerce string false to restart ownership | State load now raises; full schema, version, numeric timestamps, boolean and resource/process identities are validated. Duplicate keys at any JSON nesting level are rejected. Validate every hold before installing any. No clean fallback can erase uncertainty. |
| A model-load route can forward with no miner-stop policy, and an unregistered model hold can be ignored by inference idle restart | Reject model-load routes without a matching blocking hook; inspect all tracked resources before idle actions. These are bounded guards, not validated policy semantics or cross-resource serialization. A wildcard/no-op hook satisfies the presence check, so model hooks must remain disabled for the proposed inference-only test. |
| StopProcessAction can skip the supervisor mutex on a STOPPED snapshot while a prior serialized start is still awaiting | Fixed: always await supervisor.stop and configured verification, even if initial status is STOPPED. A deterministic delayed-start test now proves the process is stopped before the action returns. SKIPPED reporting for the initial snapshot is preserved without bypassing the mutex. |
| Diagnostics can leak nvidia-smi children on timeout/cancellation and report no measurement as 0% utilization | Kill/reap the owned query child, preserve cancellation, reject invalid/nonfinite samples, and raise on unavailable maximum utilization. Diagnostics explicitly report execution_state=unverified and restart_authorized=false. They are observations, not an upstream idle verifier. |
| Live plan uses nonexistent start/start-process commands, positional config validation, incomplete recovery syntax, wrong cooldown and image-wide taskkill rollback | Replaced with a blocked preparation checklist and accurate CLI boundaries. Removed executable live/kill/recovery recipes and unsupported safety claims. Template cooldown is 30 seconds. |

The process, lease, policy and gateway implementations were unchanged between e903cf2e and the submitted 9101ca7c. Some findings therefore expose existing Phase B limitations through new Phase C config/docs rather than representing new core-code regressions. The corrections retain generic triggers, conditions, actions, events, resource leases and existing callable APIs where practical. Safety restrictions on state loading and nonzero tolerance are intentional. Package version is 0.3.0, covering the newly added Phase C diagnose capability and reviewed behavior; entry points are unchanged.

## Remaining blockers before a supervised GO

1. **No supported coordinator-owned starter.** `serve` opens the proxy but does not launch Krig. CLI start/start-process do not exist; standalone miner pause/resume remain disabled. Implement and review an explicit same-process startup/shutdown harness or authenticated daemon control, with admission gating, exact identity, a shared-console dedicated group, verified stop and cancellation/shutdown behavior. Do not substitute an external launch or a second coordinator.
2. **No real deployment facts verified.** Review the private runtime config, actual binary/arguments, existing process/child identities and console attachment. Independently establish upstream idle and exclude all other clients/launchers/watchdogs. No claim here certifies the historical no-supervisor observation, CUDA/share-flush timing, safe power settings, or mining coexistence with Qwen's resident VRAM.
3. **General cross-resource safety is absent.** `gpu.inference` and `gpu.model_loading` are independent lease domains. Logical exclusive model claims do not block inference; pending exclusive writers have no precedence. The broader test must wait for conflict groups and process/resource transaction semantics. A narrow test could avoid this only by enforcing one inference domain/client, preloaded Qwen, disabled model hooks/operations and no independent process actions.
4. **An exact-identity abort/reconciliation procedure and explicit live authorization remain necessary.** Stop at uncertainty; never clear inhibition by restarting the coordinator, by observing low GPU use or by later successful inference. The initial future experiment should be one sequential normal completion, with interruption/recovery/crash scenarios separately scoped.

## Actual lock graph and remaining races

`reserve` updates pending/cooldown under the lease mutex, then unlocks before blocking hooks; hooks can acquire the supervisor mutex; activation subsequently uses the lease condition. Idle workers likewise release the lease mutex before emitting events and process actions. No built-in inverse nested mutex acquisition was demonstrated in this review. The submitted three-level hierarchy and `_action_lock`/pre-spawn guard were proposals, not existing code: the real supervisor has `_lock` and no LeaseManager dependency.

Holding the lease mutex across hooks would deadlock a callback that requests a lease. Adding an awaited manager check inside the supervisor mutex could invert a future manager-to-supervisor order. Existing supervisor event callbacks execute while its mutex is held, so reentrant start/stop can deadlock. Observational listeners are awaited and may hang or suppress cancellation. Same-resource timer cancellation and the fixed stop action cover bounded cases; an unrelated resource or independent start can still arrive after stop, and the idle snapshot is not an atomic check-and-spawn operation. Simultaneous cooldowns can also defer restart indefinitely. See [cross-resource analysis](CROSS_RESOURCE_SERIALIZATION.md) before implementing a hierarchy.

## Blockers specific to unattended operation

- **Durable integration is still absent.** No runtime writer, write-ahead transition ordering, single-instance authority, startup gate or crash reconciliation uses StateCodec. Config still rejects enabled persistence. The helper schema cannot represent pending/active/possibly-forwarded inference, boot/config identity, manual override, cooldown authority or durable recovery audit. Restoring inhibits does not restore leases or safe restart authority.
- Persist request/process intent before external effects; persist terminal evidence before restart eligibility. After crash, convert every possibly-forwarded nonterminal request into a hold. Missing/unreadable state keeps execution gated. Do not debounce safety writes after side effects or use droppable telemetry as the safety journal. File fsync plus replace is not a proven power-loss transaction.
- Exact psutil creation-time equality improves the current check but is not a complete durable Windows identity contract. Retain native creation FILETIME, executable/boot/instance identity and stable handles where appropriate; verify at action. Wrong/missing identity, access denial or unavailable upstream evidence must not authorize restart.
- Integrate external supervisor ownership/containment or retain a strict exclusion contract. The 0.3-second quiet window and captured-child scan cannot prevent delayed relaunch or detached/new descendants. The Phase C fake-watchdog test asserts stop success followed by relaunch; it demonstrates detection, not protection against overlap.
- Add bounded callback/lifecycle rules, true shutdown cancellation/reconciliation, crash-injection and real TCP/Windows evidence, secure state ownership/ACLs, and attributable durable operator overrides. HTTP model list, process absence and low sampled utilization are insufficient to establish earlier upstream execution termination.

See [durable requirements](DURABLE_STATE_RECOVERY.md) for the minimum transition records and startup protocol.

## Acceptable limitations for a future tightly controlled supervised test

After the supervised blockers are closed, one present operator may run an explicitly authorized, isolated, single-client normal-path experiment using an already loaded Qwen model. It may defer automatic crash recovery only if any crash/restart aborts the experiment and mining stays stopped until independent reconciliation. It may defer native endpoints/tools, model mutation, multiple resources, watchdogs, automated recovery and telemetry persistence. Forceful shutdown is not required to make the test pass; inability to verify graceful stop must veto forwarding and abort.

This does not make the current preparation executable. The [revised acceptance checklist](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md) records unmet gates.

## Telemetry T1 reconciliation — assessment only, no merge performed

Both submitted branches have merge base e903cf2e and one independent commit each: Phase C 9101ca7c, T1 dd8dd7ff. T1 adds telemetry models/schema/SQLite storage/collector/exporters/config and CLI commands, plus gateway storage lifecycle wiring. Phase C adds diagnose/NVIDIA monitoring, recovery helpers, tests and preparation docs; current review corrections add the guards described above.

For a separately authorized integration:

1. Preserve both existing branch tips/worktrees. Create an isolated integration branch from this reviewed Phase C result, then bring in T1's single commit only after authorization. No reset/replacement of either workstream is needed.
2. Resolve CLI changes by preserving diagnose **and** requests/stats/telemetry parsing and dispatch; do not choose a whole-file ours/theirs result. Preserve both handoffs/plan indexes. T1 config additions must retain all current validation, force/adoption restrictions and persistence-disabled boundary.
3. Gateway lifecycle wiring must retain the Phase B cleanup owner, cancellation shielding, completion detection, non-clearing inhibition, authenticated override, current model-policy gate and disabled redirect behavior. Add telemetry resource cleanup with try/finally, and test normal and failing lifespan exits. Storage enablement/path selection must be explicit for the experiment; T1 defaults to enabled with relative telemetry.db.
4. Keep telemetry observational and separate from the authoritative safety journal. T1's bounded queue can drop records; SQLite WAL/synchronous NORMAL and successful enqueue do not establish crash-safe safety-state persistence. A missing sample is not zero or proof of idle.
5. Verify actual event mapping: T1 collector subscribes to operation.* and model.*, while the gateway emits lmstudio.inference_* / lmstudio.model_load_*. Current T1 gateway diff only wires storage lifecycle. Request/model recording therefore needs explicit adapter mapping and end-to-end mock-gateway-to-database tests; synthetic operation events alone do not prove integration. Resource acquired/released payloads contain nested lease data, which also needs normalization.
6. Run the combined offline safety and telemetry suites, CLI/config contracts, saturation/write-failure/drop behavior, privacy checks and static analysis. Specifically retain uncertain A + successful B, cancellation/cleanup, active-claim recovery rejection, model guard, PID equality, and corrupt/duplicate state regressions. Inspect history and changed paths before a separate merge decision. No combined validation result is claimed here.

## Deferred improvements

Full T1 review/usage instrumentation and export polish, GPU partial-field availability and richer error reporting, callback API ergonomics, packaging/dependency-minimum matrix and coverage measurement may be deferred. A GPU query kill/wait OS error can still propagate rather than returning unavailable; this is a robustness limitation, not a false idle result. No readiness verdict depends on diagnostics completing successfully. General identity containment, crash recovery and arbitration are blockers, not polish.

## Validation and commit evidence

Submitted baseline: **121 passed in 2.49s**, Ruff check clean and Mypy clean (14 source files). Repository-format check at 120 columns reported four files requiring reformat; Gemini's narrower/default-format claim was not the repository's format check.

Corrected result: **151 passed in 2.56s** (30 added review cases), Ruff check clean, Ruff format clean (30 files), Mypy clean (14 source files), Git whitespace check clean. Failing-before-fix regressions covered identity tolerance, missing/corrupt/schema/duplicate-key state, timeout/cancellation cleanup, invalid telemetry, model bypass/holds, template group mode and start/stop interleaving. A final independent read-only reviewer checked the lifecycle/lock claims and corrections, including the stop-action fix. No coverage percentage, clean-package install, live process/inference or combined T1 validation is claimed.

From the Phase C worktree root:

```powershell
$python = "C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe"
& $python -m pytest modules/resource_coordinator/tests -o addopts= -q --basetemp=modules/resource_coordinator/.pytest_tmp_root --tb=short
& $python -m ruff check modules/resource_coordinator
& $python -m ruff format --check --line-length 120 modules/resource_coordinator
& $python -m mypy --ignore-missing-imports modules/resource_coordinator/resource_coordinator
git diff --check
```

The local correction commit is the commit containing this report; its hash is provided in the final handoff message. Reviewed source commit is 9101ca7c; prior safety baseline is e903cf2e; T1 remains dd8dd7ff. Next action: review NO-GO and authorize a narrowly scoped implementation of the missing lifecycle/admission path or further arbitration/recovery work. No live action, merge or push is implied.

Primary references: Microsoft [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes), [console control events](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent), and [process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags). These establish API semantics; they are not evidence of actual Krig/CUDA behavior.
