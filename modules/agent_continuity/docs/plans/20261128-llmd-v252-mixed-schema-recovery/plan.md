# LLMD 2.5.2 Mixed-Schema Recovery Plan

> **For agentic workers:** Implement in focused test-first steps and keep each safety boundary independently verifiable.

**Goal:** Prevent mixed-version wrappers from corrupting or losing lifecycle state, recover only exact interrupted associations, and make installation/schema conflicts diagnosable without changing production state.

**Architecture:** Keep package version and registry schema compatibility as separate facts. Add a read-only preflight/diagnostic view over the active executable, installed distributions, schema metadata, and process ownership evidence. Extend the existing pending-launch recovery path for `continue`; preview stays read-only and apply revalidates exact identity and liveness before association or resume.

**Tech Stack:** Python 3.11+, SQLite event materializer, argparse CLIs, pytest, guarded provider subprocesses.

**Spec:** User handoff dated 2026-11-28, “Mixed-version lifecycle reliability, deployment compatibility, safe interrupted-association recovery and installation diagnostics.”

## Global Constraints

- No main merge, production install, production registry rebuild, schema downgrade, active-session termination, live provider execution, or native allocation activation.
- Never replace an ambiguous session or overwrite a conflicting association.
- Previews and diagnostics are read-only; uncertain process enumeration fails closed.
- Preserve cwd, worktree, provider, permission, workflow, and instruction metadata.

## Review Focus

- Schema-3 wrapper on schema-4 registry: prove actual historical dispatcher fails before lifecycle reporting and do not imply current package can repair an already-running process.
- Interrupted pending launch: exact provider evidence must identify the reserved session; missing/unknown evidence must not mutate state.
- Recovery/continue race: serialize competing applies and reject stale selection, reservation, or liveness evidence.
- Running session: refuse resume and preserve the live association.
- Installation ambiguity: report executable/package path and schema compatibility without changing PATH or installations.

---

### Task 1: Reproduce mixed-schema incident

**Files:** Tests and disposable-registry fixture under `tests/`; no production data.
- [ ] Locate the actual 2.1.2 dispatcher commit and reproduce schema-3 writer versus schema-4 reader with a guarded provider process.
- [ ] Capture which lifecycle events/reservations existed when the wrapper failed and identify exit-bookkeeping boundaries.

### Task 2: Safe preflight and diagnostics

**Files:** `agent_continuity/` CLI/diagnostics and focused CLI tests.
- [ ] Add read-only install resolution and schema compatibility diagnostics.
- [ ] Add version-aware preflight that distinguishes package upgrade from schema transition and blocks transition when old writers are active or ownership cannot be established.

### Task 3: Continue through exact pending recovery

**Files:** `agent_continuity/dispatcher_cli.py`, `dispatcher.py` only if needed, and dispatcher/recovery tests.
- [ ] Preview describes a recoverable exact pending association without mutation.
- [ ] Apply revalidates pending identity, slot selection, provider/environment/session evidence, reservation freshness, and liveness before recovery and continue.
- [ ] Reject running sessions, unknown process enumeration, stale reservations, conflicting selection, and concurrent second recovery; preserve all launch metadata.

### Task 4: Qualification and handoff

**Files:** Plan status/checklist and focused docs as needed.
- [ ] Run focused incident and recovery tests, then applicable module and CLI suites plus Ruff and diff hygiene.
- [ ] Record exact commands, historical reproducer, safe procedure for existing schema-3 wrappers, and remaining 2.5.2 release blockers.
- [ ] Commit and push the task branch only after qualification; do not merge or deploy.
