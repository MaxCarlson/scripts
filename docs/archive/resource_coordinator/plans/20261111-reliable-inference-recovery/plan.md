# Reliable Inference Recovery Implementation Plan

**Goal:** Make operator recovery use the protected shared credential, make uncertain operations visible and diagnosable, and automatically release only when the gateway has authoritative terminal evidence.

**Architecture:** Extend the existing gateway/lease/durable-state path rather than adding a parallel coordinator. A terminal model-load event is authoritative for that request; timeout, disconnect, idle inventory, and GPU samples remain uncertain. The recovery CLI reads an existing validated token without creating one, while the server accepts configured legacy recovery credentials and diagnoses mismatches without exposing secrets.

**Tech Stack:** Python 3.12, Starlette, HTTPX, AnyIO, pytest, existing Resource Coordinator lease manager and atomic state journal.

**Spec:** User request, “Resource Coordinator — Reliable Inference Recovery, Transparent Authentication, and Miner Safety”.

## Global Constraints

- Do not contact or mutate production services, KRig, LM Studio, credentials, Scheduled Tasks, GPU configuration, or WSL.
- Never treat a timeout, local disconnect, empty lease set, GPU sample, or model inventory as proof of backend termination.
- Clear only the matching request/holder inhibition after authoritative terminal evidence or explicit authenticated operator override.
- Preserve durable journal compatibility and existing CLI/HTTP aliases and JSON fields.
- Never expose tokens, prompts, or raw sensitive request bodies in diagnostics.

## Review Focus

- A request timeout or disconnect after forwarding remains inhibited and has a durable request-specific recovery record.
- A model-load terminal event cannot clear a different or newer inhibition.
- An operator recovery credential mismatch fails closed without leaking either credential.
- Active/pending claims, manual/gaming holds, journal failure, and a newer inhibition block recovery and restart.
- Service restart restores unresolved uncertainty without starting the managed miner.

## Planned Files

- `resource_coordinator/cli.py`: shared-token recovery client; preserve environment override precedence and `-f` intent.
- `resource_coordinator/core/operator_credentials.py`: expose non-creating validated credential read only if existing `load_token()` semantics do not meet recovery needs.
- `resource_coordinator/adapters/lmstudio/gateway.py`: model-load terminal detection, safe failure diagnostics, stable recovery/status route shape, exact holder checks.
- `resource_coordinator/core/leases.py`: add atomic clear-by-holder/idle guards only where current contracts are insufficient.
- `resource_coordinator/core/durable_state.py`: backward-compatible recovery diagnostic fields only if existing request journal cannot represent required evidence.
- Existing gateway, credential, service, lease, durable-state, CLI and presentation tests; add focused mock-server integration coverage.
- `docs/plans/20261111-reliable-inference-recovery/STATUS.md`: implementation and validation evidence.

## Tasks

### Task 1 — Credential-backed recovery CLI and server compatibility

1. Add tests proving protected-file recovery works without environment variables and does not create credentials; preserve explicit operator/recovery overrides.
2. Add rejection tests for missing/invalid/mismatched/insecure credentials, unauthorized direct HTTP calls, and secret redaction.
3. Run those tests red in the candidate venv.
4. Implement minimal shared credential-provider use and server-side token matching without file permission mutation or implicit provisioning.
5. Run gateway/CLI/credential tests; record results and commit.

### Task 2 — Terminal evidence and actionable request diagnostics

1. Test valid/malformed/partial `model_load.end`, synchronous `status: loaded`, nonterminal progress, upstream HTTP errors, connect/read timeout, and disconnect classification.
2. Test request-specific diagnostics preserve legacy phase values and JSON fields while adding safe timing/type/status/evidence metadata.
3. Implement typed terminal classification and redacted diagnostics. Only recognized authoritative terminal events may resolve uncertainty.
4. Add a single durable recovery record keyed by request/holder, with evidence timestamps and operator action guidance; maintain read compatibility with existing journals.
5. Run focused gateway, durable-state, lease, and presentation tests; commit.

### Task 3 — Safe reconciliation and explicit recovery state

1. Test attribution, stale-holder rejection, competing active/pending claims, all guarded GPU resources, manual/gaming/global holds, restart after uncertain journal state, and operator override audit.
2. Add bounded read-only reconciliation only for a documented authoritative backend capability. If the installed API offers no such capability, report `uncertain` and actionable operator steps without polling aggressively.
3. Make holder validation, durable resolution, inhibition clear, cooldown eligibility and restart guards atomic or fail closed on persistence failure.
4. Extend existing status/health and authenticated recover responses additively; do not create overlapping CLI families.
5. Run lifecycle and restart regressions; commit.

### Task 4 — End-to-end fake-miner regression and interface contract

1. Build a controllable mock LM Studio HTTP server and fake managed miner fixture using isolated state paths and deterministic clocks.
2. Cover successful synchronous/streaming load, inference, uncertain timeout, authoritative terminal reconciliation, explicit authenticated recovery, rejected recovery, disconnect/cancellation, service restart with unresolved state, and repeated/racing operations.
3. Document the read-only recovery/status response and authenticated recovery request/response contract for Resource Monitor; preserve existing routes.
4. Run relevant suites, Ruff on changed files, compilation and diff checks; review the full diff and update status.
5. Commit final scoped changes; do not merge or deploy.

## Initial Checkpoint

- Base: `9102815920eff843c724f4f98a7957d94d46fbb2`.
- Branch: `agent/resource-coordinator-inference-recovery-20261111`.
- Worktree: `.worktrees/resource-coordinator-inference-recovery-20261111`.
- Implementation checkpoint: `927fa3e3051f81ae9c19123974376527c236914f`.
- Shared-token end-to-end regression checkpoint: `da504cf54341052a0a1ee74fedded90628a7b40b`.
- CLI-to-ASGI protected-file recovery test: `c310177da304f727603d7b923f5a5f6b50da4f30`.

## Stage Outcome

- **Task 1 — completed.** Recovery CLI uses a non-creating secure shared-credential read, preserves explicit overrides, and redacts credential echoes. The server authenticates shared and legacy recovery credentials, with file ACL validation for the on-disk shared token.
- **Task 2 — completed for implemented transport paths.** The gateway distinguishes connect/read/transport failures, records additive request diagnostics in the existing journal `details`, and classifies terminal model-load success/failure separately from uncertainty. Existing phase values and JSON fields remain intact.
- **Task 3 — safe fallback completed; automatic post-timeout reconciliation remains unsupported.** No authoritative per-operation status/cancel API was established, so uncertain timeouts/disconnects remain inhibited and visible. No speculative inventory/GPU probes or timer-based release were added. Explicit override continues to resolve all unresolved journal requests for the selected resource atomically with clearing its in-memory inhibition, subject to existing active/pending/readiness/global restart guards.
- **Task 4 — focused coverage and contract completed; live acceptance not performed.** Mocked timeout, streaming terminal, fake-miner cooldown/restart, status, authentication, and journal audit paths are covered. Broader arbitration/restart/cancellation suites passed as recorded in `STATUS.md`. Real production credentials, Scheduled Tasks, UAC, miner, LM Studio, GPU, and WSL were not used.

See `STATUS.md` for exact commands, results, the baseline-reproduced GPU-idle lifecycle failure, and remaining acceptance limits. No merge or deployment is authorized by this task.
