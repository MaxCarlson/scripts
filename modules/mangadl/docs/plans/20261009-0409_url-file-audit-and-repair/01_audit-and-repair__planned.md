# Stage 1 — URL-file Audit and Repair Plan

## Status

Approved, implemented, and focused validation passed on 2026-10-09. This
stage now pauses for user manual validation before Stage 2, per repository
instructions.

## Scope

1. Define structured URL audit outcomes and stable JSON fields, preserving URL
   input provenance, backend route, folder matches, expected-image evidence,
   local integrity findings, and repair eligibility.
2. Confirm an audit-only file flag that supports the requested
   `mangadl audit -u URLFILE.txt` form without changing `run -u/--url`, while
   retaining existing `audit -i/--input-file` and alias behavior.
3. Establish dry-run as the default and ensure metadata probes do not download
   payloads or change the archive. Require a separate explicit apply option for
   any repair work.
4. Set fail-closed semantics: unknown expected counts, unsupported adapters,
   ambiguous folders, broad collections, active partial owners, and
   unverifiable archive mappings cannot be presented as complete or repaired.
5. Record a focused test matrix and implementation dependencies for the
   adapter, integrity, planner, executor, Kavita continuity, and docs stages.

## Files expected during implementation

This is a planning boundary only; names may change after approved inspection.

- Existing input/routing and audit code: `mangadl/input.py`,
  `mangadl/backends.py`, `mangadl/destination_audit.py`, `mangadl/cli.py`,
  `mangadl/cli_core.py`, `mangadl/cli_structure.py`.
- Existing lifecycle and safety code: `mangadl/manager.py`,
  `mangadl/worker.py`, `mangadl/worker_core.py`, `mangadl/state.py`,
  `mangadl/partial_safety.py`, `mangadl/partial_reconcile.py`,
  `mangadl/scratch.py`, `mangadl/repair.py`.
- Focused suites: `tests/destination_audit_test.py`,
  `tests/input_test.py`, `tests/backends_test.py`, `tests/repair_test.py`,
  `tests/worker_test.py`, `tests/partial_safety_test.py`,
  `tests/scratch_test.py`, `tests/kavita_assignment_test.py`, plus new
  adapter/integrity/repair tests as approved.
- Public docs and dispatcher: `README.md`, `docs/README.md`, module plan
  handoffs, and `validation-targets.json` if commands or targets change.

## Dependencies and gates

- Stage 2 must prove which backends can enumerate complete expected page
  identities before Stage 3 can label results complete.
- Stage 3 defines which files are valid and binds them to expected identities
  before Stage 4 can plan network repair.
- Stage 4 must settle exact gallery-dl archive key targeting, reversible
  quarantine, and normal/scratch partial lifecycle before implementation.
- Stages 1–4 require user approval of this plan before code changes. Live
  acceptance additionally requires a bounded URL set, destination, and
  transfer-volume review after the implementation and preview are concrete.

## Stage 1 verification

See `STATUS.md` for exact commands and results. Subsequent implementation
should add and run focused tests for each stage, then the full MangaDL suite,
CLI help/JSON checks, compile/Ruff, and the repository validation dispatcher
target. Exact commands/results belong in `STATUS.md` after execution.
