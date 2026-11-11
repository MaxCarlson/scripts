# Trusted Maintenance Restoration Verification Plan

> **For agentic workers:** Use a test-first implementation sequence. Keep H2A integration and H2C verifier evidence in separate commits.

**Goal:** Permit ordinary maintenance release only after Resource Coordinator independently verifies configured GPU settings and optimizer-owned miner termination.

**Architecture:** Preserve the v0.13 maintenance session state machine and verifier extension point. Add a disabled-by-default, bounded NVML observer, an explicit allowlisted tuning scope and exact process registration, then run release verification outside the manager lock and revalidate the same session before durable release.

**Tech Stack:** Python 3.12, asyncio, psutil, optional `nvidia-ml-py`, pytest.

**Spec:** `docs/plans/20261111-gpu-maintenance-sessions/STATUS.md` and the H2A/H2C handoff.

## Global Constraints

- Never mutate or inspect production GPU/coordinator/miner state for acceptance.
- Automatic release remains disabled unless explicitly configured and every required observation is supported.
- Client restoration assertions are inputs, not independent proof.
- Fixed/locked-clock scope remains ineligible without a reliable getter.
- External processes are observed, never adopted, terminated, or restarted.
- Mining is read-only; no main merge or deployment.

## Review Focus

- Missing or unsupported observations must preserve the hold; test disabled observer, unsupported dimension, timeout, and malformed sample.
- Stale verification must not release a newer session; test expiry and competing release while a verifier is paused.
- PID reuse must not be mistaken for a live or terminated registered process; test exact creation-time and executable identity.
- Old maintenance records must remain fail-closed; test v0.13 records without baseline/scope.
- Client-only evidence must never release; test assertion without a configured independent verifier.

## File Map

- `resource_coordinator/core/restoration.py`: structured observation, NVML adapter, process observer, and policy comparison.
- `core/config.py`, `core/service.py`, `core/maintenance.py`, `core/durable_state.py`, and `adapters/lmstudio/gateway.py`: validated configuration, construction, baseline capture, process registration, non-blocking release verification, and durable evidence.
- `tests/test_restoration.py`, `tests/test_maintenance.py`, and `tests/test_config.py`: deterministic observer and lifecycle regression coverage.
- `docs/MAINTENANCE_SESSIONS.md` and this plan's `STATUS.md`: compatibility contract and evidence.
- `pyproject.toml`, `resource_coordinator/__init__.py`: optional NVML extra and v0.14.0 feature version.

## Tasks

### Task 1 — H2A integrated-source checkpoint

- [x] Run focused maintenance, arbitration, state, gateway, supervision, recovery, and Windows installation suites with isolated temp roots.
- [x] Classify prior exploratory failures without invoking live-mode/production-listener cases.
- [x] Record exact merged SHA, source coverage, limitations, and baseline comparisons in `STATUS.md`.
- [x] Commit this status checkpoint before H2C source edits (`b794d0e0c13b5aeab49adaf57aada63e4ac97f0e`).

### Task 2 — Observation and scope contracts

- [x] Add focused tests for capability classifications, per-dimension exact comparisons, UUID/driver mismatch, and fail-closed unsupported fields.
- [x] Implement injectable observer/process protocols and optional native NVML read-only adapter.
- [x] Add strict disabled-by-default config with UUID, allowed dimensions, known miner executable names, and bounded observation timeout.
- [x] Verify old config loads with verification disabled and reject invalid enabled policy.

### Task 3 — Durable baseline and process identity

- [x] Add tests proving baseline capture follows verified RC miner stop and precedes token grant.
- [x] Persist baseline and explicit tuning scope atomically; baseline errors retain acquisition hold and issue no grant.
- [x] Add authenticated, token-bound process-registration endpoint that independently re-reads PID, creation time, and executable identity.
- [x] Validate durable baseline/scope/registration shapes and reject stale or reused PIDs at release.

### Task 4 — Race-safe trusted release

- [x] Add tests for valid release, surviving process, unsupported scope, timeouts, and expiration race; existing maintenance regressions cover cancellation, duplicate release, and unrelated holds.
- [x] Refactor release into short locked transitions, off-loop bounded observation, then locked exact-session/state revalidation before commit.
- [x] Preserve the GPU admission fence and restart hold on any failure; only normal existing cooldown/supervision may restart the managed miner.

### Task 5 — Contract, compatibility, and final validation

- [x] Document configuration, evidence semantics, process registration request, fixed-clock limitation, and required Mining follow-up.
- [x] Review H2B release/request shape read-only and record exact client changes still needed.
- [x] Run focused and broad relevant suites, Ruff, compilation, and `git diff --check`.
- [x] Commit H2C separately (`873a49382a5e03da47f793608d3519f7e69da646`), review full branch diff, push the isolated branch, and record final evidence.
