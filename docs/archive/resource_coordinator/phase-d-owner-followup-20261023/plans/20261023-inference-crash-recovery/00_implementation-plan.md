# Inference Crash-Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Persist inference operation intent and outcomes so a coordinator restart cannot silently remove a restart inhibition for possibly active upstream work.

**Architecture:** Add a synchronous SQLite safety journal separate from observational telemetry. Configure it explicitly, initialize it only through an explicit local CLI command, commit request phases before side-effect boundaries, and restore every unresolved operation as a startup inhibition. Do not replay requests or infer upstream idle.

**Tech Stack:** Python 3.10+, standard-library `sqlite3`, existing Starlette/AnyIO gateway, pytest.

**Spec:** [Inference crash-recovery design](../../INFERENCE_DURABLE_STATE_DESIGN.md).

## Global Constraints

- Journal only bounded request metadata; never store request bodies, prompts, completions, authorization headers, or credentials.
- A journal write must complete before its associated side effect; journal failure prevents the side effect or closes admission and preserves inhibition.
- Missing, unreadable, corrupt, or unsupported journal state must fail closed; service startup must not initialize a clean journal implicitly.
- Unresolved requests remain inhibited until explicit local operator resolution with actor and reason recorded.
- Telemetry remains a separate, lossy observational stream and cannot authorize restart or recovery.
- No live LM Studio, miner, model, GPU, or host process operation is in scope.
- This slice does not claim unattended readiness; process-action journaling, cross-resource arbitration, single-instance authority, process containment, strict shutdown bounds, and real Windows/TCP/crash evidence remain open.

## Review Focus

- Disk errors before a process-stop hook or upstream send must veto that action; test each write boundary.
- Crash after `possibly_forwarded` but before completion must become unresolved startup inhibition; test recovery from each nonterminal phase.
- Completion must be durable before lease release; test event ordering for normal and uncertain responses.
- Missing, corrupt, unsupported, or duplicate journal data must never initialize as clean; test initialization and startup separately.
- Operator resolution must target one unresolved request, require explicit force/reason, and retain an attributable audit record; test invalid and repeated resolutions.

---

### Task 1: Safety journal store and configuration

**Files:**
- Create: `resource_coordinator/core/safety_journal.py`
- Modify: `resource_coordinator/config.py`
- Test: `tests/test_safety_journal.py`
- Test: `tests/test_config.py`

**Interfaces:**
- `SafetyJournal.initialize(path: Path | str) -> None` creates a new versioned SQLite journal and refuses to overwrite an existing file.
- `SafetyJournal(path: Path | str)` stores the path without creating a file.
- `SafetyJournal.open_existing() -> None` opens and validates an existing journal; it never creates or initializes one implicitly.
- `JournalRequest` is an immutable typed record containing request ID, resource, path, phase, and timestamps only.
- `begin_request(request_id: str, resource: str, path: str, started_at: float) -> None` records phase `reserved`.
- `mark_possibly_forwarded(request_id: str, updated_at: float) -> None` moves a reserved request to `possibly_forwarded` and rejects invalid transitions.
- `record_outcome(request_id: str, outcome: str, updated_at: float) -> None` records one terminal outcome: `not_forwarded`, `confirmed_complete`, or `uncertain`; `confirmed_complete` is allowed only after `possibly_forwarded`.
- `list_unresolved() -> list[JournalRequest]` returns all nonterminal request records in stable order.
- `resolve_request(request_id: str, operator: str, reason: str, resolved_at: float) -> None` records an explicit override and leaves `upstream_idle_verified` false.
- `close() -> None` closes the connection.
- Add optional `service.safety_journal_path` to `ServiceConfig`; empty means disabled. `CoordinatorSystem` and `build_system` expose a journal only when configured, without opening or creating the file during assembly.

- [ ] **Step 1: Write failing storage tests** for explicit initialization, refusal to overwrite, versioned schema validation, valid phase transitions, invalid transitions, unresolved listing, audited resolution, corrupt/missing database rejection, and metadata-only persistence.
- [ ] **Step 2: Run the targeted tests** with `python -m pytest modules/resource_coordinator/tests/test_safety_journal.py -q`; confirm failures identify the missing store.
- [ ] **Step 3: Implement the SQLite journal and typed request record** with transactions for each phase transition, strict metadata validation, no automatic retention, and no dependency on `TelemetryStorage`.
- [ ] **Step 4: Add config parsing/validation tests** proving the path is optional and preserved when set, and the system factory does not create the database.
- [ ] **Step 5: Run targeted storage/config tests** and confirm they pass.

### Task 2: Managed startup recovery and local journal commands

**Files:**
- Modify: `resource_coordinator/config.py`
- Modify: `resource_coordinator/core/service.py`
- Modify: `resource_coordinator/adapters/lmstudio/gateway.py`
- Modify: `resource_coordinator/cli.py`
- Test: `tests/test_service_lifecycle.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_factory_gateway_integration.py`

**Interfaces:**
- Add `resource-coordinator state init`, `state unresolved`, and `state resolve` commands using the path from `service.safety_journal_path` in `-c/--config`.
- `state init` creates only a missing journal; existing files are never overwritten.
- `state resolve` requires `-f/--force`, `-r/--request-id`, `-o/--operator`, and `-n/--reason`; it affects only that unresolved request and reports that upstream idle was not verified.
- Gateway lifespan calls `open_existing()` before `CoordinatorService.start` and closes it during shielded shutdown.
- `CoordinatorService.start` restores each unresolved request as a `gpu.inference` restart inhibition before preflight; unresolved state moves the service to `RECONCILIATION_REQUIRED` and prevents readiness.

- [ ] **Step 1: Write failing startup tests** for unresolved rows restoring an inhibition, clean initialized state allowing ordinary preflight, and missing/corrupt state failing closed without database creation.
- [ ] **Step 2: Run the targeted lifecycle tests** and confirm they fail on current startup wiring.
- [ ] **Step 3: Integrate journal open/restore/close into managed lifespan and service startup**; preserve existing telemetry lifecycle and service ownership behavior.
- [ ] **Step 4: Write failing CLI tests** for init, unresolved listing, required force/reason/operator/request ID, and request-specific resolution.
- [ ] **Step 5: Implement the three local state commands** with short and long forms for all user-facing options; do not add an HTTP recovery path for an unready service.
- [ ] **Step 6: Run targeted lifecycle, factory, and CLI tests** and confirm they pass.

### Task 3: Write-ahead integration in the inference gateway

**Files:**
- Modify: `resource_coordinator/adapters/lmstudio/gateway.py`
- Test: `tests/test_factory_gateway_integration.py`
- Test: `tests/phase_d_safety_review_test.py`

**Interfaces:**
- Before `emit_blocking`, commit `reserved` for the request.
- Immediately before `client.send`, commit `possibly_forwarded`.
- In shielded cleanup, commit `not_forwarded`, `confirmed_complete`, or `uncertain` before emitting final cleanup/releasing the reservation.
- If `reserved` or `possibly_forwarded` cannot be committed, do not cross the next side-effect boundary.
- If outcome persistence fails, latch emergency abort and restart inhibition before releasing the in-memory reservation; leave the durable request unresolved.
- When the journal is not configured, preserve current behavior.

- [ ] **Step 1: Add ordering regressions** whose fake journal records call order relative to blocking policy hooks, upstream send, completion handling, and lease release.
- [ ] **Step 2: Add disk-failure regressions** proving pre-send failures prevent upstream forwarding and outcome failures abort and inhibit restart.
- [ ] **Step 3: Run the new gateway regressions** and confirm they fail before implementation.
- [ ] **Step 4: Add the journal transitions to the gateway** without changing completion classification, admission rechecks, streaming cleanup shielding, or request privacy.
- [ ] **Step 5: Run gateway and Phase D safety tests** and confirm they pass.

### Task 4: Documentation, full focused verification, and commit

**Files:**
- Modify: `docs/HANDOFF.md`
- Modify: `docs/plans/HANDOFF.md`
- Modify: `docs/DURABLE_STATE_RECOVERY.md`
- Modify: `docs/PHASE_D_SAFETY_REVIEW.md`
- Modify: `docs/plans/20261023-inference-crash-recovery/STATUS.md`
- Modify: `docs/plans/20261023-inference-crash-recovery/checklist.md`

- [ ] **Step 1: Document configuration, explicit initialization, unresolved startup behavior, local operator resolution, limitations, and remaining NO-GO blockers.**
- [ ] **Step 2: Run focused verification:** `python -m pytest modules/resource_coordinator/tests/test_safety_journal.py modules/resource_coordinator/tests/test_config.py modules/resource_coordinator/tests/test_cli.py modules/resource_coordinator/tests/test_service_lifecycle.py modules/resource_coordinator/tests/test_factory_gateway_integration.py modules/resource_coordinator/tests/phase_d_safety_review_test.py -q`.
- [ ] **Step 3: Run the full module suite** with an isolated module-local `--basetemp`, plus Ruff check, Ruff format check at 120 columns, Mypy, and `git diff --check`.
- [ ] **Step 4: Review staged paths, stage only the resource-coordinator feature/tests/docs, and commit if all checks pass. Do not push or merge.**

## Safety boundary after this plan

Even after these tasks pass, the coordinator remains NO-GO for unattended operation. Durable process start/stop intent/results, cross-resource transactions, single-instance authority, external process containment, total shutdown deadlines, and real Windows/TCP/crash acceptance remain separate work.
